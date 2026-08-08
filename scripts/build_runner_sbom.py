"""Build an offline CycloneDX inventory for the local LabOps Runner images.

The script never contacts a registry.  It queries already-built images through
Docker with networking disabled and records image IDs, Python distributions,
and Debian packages.  Debian license texts remain authoritative in
``/usr/share/doc/*/copyright`` inside each image; this inventory intentionally
does not guess SPDX identifiers for them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path


IMAGES = (
    "labops/pytorch-cpu-runner:0.1.0",
    "labops/pytorch-cpu-runner:0.2.0",
)

KNOWN_PYTHON_LICENSES = {
    "filelock": "MIT",
    "fsspec": "BSD-3-Clause",
    "jinja2": "BSD-3-Clause",
    "markupsafe": "BSD-3-Clause",
    "mpmath": "BSD-3-Clause",
    "networkx": "BSD-3-Clause",
    "pip": "MIT",
    "setuptools": "MIT",
    "sympy": "BSD-3-Clause",
    "torch": "BSD-3-Clause",
    "typing-extensions": "PSF-2.0",
    "wheel": "MIT",
}


def docker_path() -> str:
    found = shutil.which("docker")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        if candidate.exists():
            return str(candidate)
    raise SystemExit("Docker CLI not found")


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout


def inspect_image(docker: str, image: str) -> dict:
    return json.loads(run(docker, "image", "inspect", image))[0]


def python_packages(docker: str, image: str) -> list[dict[str, str]]:
    code = (
        "import importlib.metadata as m,json;"
        "print(json.dumps(sorted([{'name':d.metadata['Name'],'version':d.version} "
        "for d in m.distributions()],key=lambda x:x['name'].lower())))"
    )
    raw = run(
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--entrypoint",
        "python",
        image,
        "-c",
        code,
    )
    return json.loads(raw)


def debian_packages(docker: str, image: str) -> list[dict[str, str]]:
    query = "dpkg-query -W -f='${binary:Package}\\t${Version}\\t${Architecture}\\n'"
    raw = run(
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--entrypoint",
        "sh",
        image,
        "-c",
        query,
    )
    packages = []
    for line in raw.splitlines():
        name, version, arch = line.split("\t", 2)
        packages.append({"name": name, "version": version, "arch": arch})
    return sorted(packages, key=lambda item: item["name"])


def os_release(docker: str, image: str) -> dict[str, str]:
    raw = run(
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--entrypoint",
        "sh",
        image,
        "-c",
        "cat /etc/os-release",
    )
    values = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


def component_ref(kind: str, name: str, version: str, arch: str = "") -> str:
    suffix = f"@{version}" + (f"?arch={arch}" if arch else "")
    return f"pkg:{kind}/{name.lower().replace('_', '-')}" + suffix


def build_document(docker: str) -> dict:
    components: dict[str, dict] = {}
    dependencies: list[dict] = []
    image_records = []

    for image in IMAGES:
        details = inspect_image(docker, image)
        image_id = details["Id"].removeprefix("sha256:")
        image_ref = f"pkg:oci/{image.split(':')[0]}@sha256:{image_id}"
        os_info = os_release(docker, image)
        py_packages = python_packages(docker, image)
        os_packages = debian_packages(docker, image)
        child_refs = []

        components[image_ref] = {
            "type": "container",
            "bom-ref": image_ref,
            "name": image.split(":")[0],
            "version": image.rsplit(":", 1)[1],
            "hashes": [{"alg": "SHA-256", "content": image_id}],
            "properties": [
                {"name": "labops:runtime-network", "value": "none"},
                {"name": "labops:inventory-method", "value": "offline docker run --network none"},
                {"name": "labops:os", "value": f"{os_info.get('PRETTY_NAME', 'unknown')}"},
            ],
        }

        for item in py_packages:
            name = item["name"]
            version = item["version"]
            ref = component_ref("pypi", name, version)
            comp = {
                "type": "library",
                "bom-ref": ref,
                "name": name,
                "version": version,
                "purl": ref,
                "properties": [{"name": "labops:package-layer", "value": "python"}],
            }
            license_id = KNOWN_PYTHON_LICENSES.get(name.lower())
            if license_id:
                comp["licenses"] = [{"license": {"id": license_id}}]
            components[ref] = comp
            child_refs.append(ref)

        distro = os_info.get("ID", "debian")
        distro_version = os_info.get("VERSION_ID", "unknown")
        for item in os_packages:
            ref = component_ref("deb", item["name"], item["version"], item["arch"])
            components[ref] = {
                "type": "library",
                "bom-ref": ref,
                "name": item["name"],
                "version": item["version"],
                "purl": ref,
                "properties": [
                    {"name": "labops:package-layer", "value": "os"},
                    {"name": "labops:distro", "value": f"{distro}:{distro_version}"},
                    {"name": "labops:license-source", "value": "/usr/share/doc/<package>/copyright"},
                ],
            }
            child_refs.append(ref)

        dependencies.append({"ref": image_ref, "dependsOn": sorted(set(child_refs))})
        image_records.append(
            {
                "image": image,
                "image_id": details["Id"],
                "created": details.get("Created"),
                "python_packages": len(py_packages),
                "debian_packages": len(os_packages),
            }
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "tools": {"components": [{"type": "application", "name": "build_runner_sbom.py", "version": "1.0"}]},
            "component": {
                "type": "application",
                "name": "LabOps Guard Runner image inventory",
                "version": "0.3.0-rc1",
            },
            "properties": [
                {"name": "labops:network-access", "value": "disabled"},
                {"name": "labops:scope", "value": "local images; not a redistribution approval"},
                {"name": "labops:image-summary", "value": json.dumps(image_records, ensure_ascii=False)},
            ],
        },
        "components": sorted(components.values(), key=lambda item: item["bom-ref"]),
        "dependencies": dependencies,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/compliance/runner-sbom.json"),
        help="CycloneDX JSON output path",
    )
    args = parser.parse_args()
    document = build_document(docker_path())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("runner SBOM written")


if __name__ == "__main__":
    main()
