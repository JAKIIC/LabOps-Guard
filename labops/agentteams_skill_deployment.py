"""Fail-closed deployment planning for the seven existing AgentTeams Skills."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from labops.contracts import validate_document
from labops.skill_registry import list_skills


class AgentTeamsSkillDeploymentError(ValueError):
    """Raised when the runtime Skill mapping cannot be trusted."""


class DockerSkillRuntime:
    """Narrow Docker boundary used only for explicit Reviewer Skill deployment."""

    def _run(self, args: list[str], *, allowed_returncodes: set[int] | None = None) -> subprocess.CompletedProcess[str]:
        allowed = allowed_returncodes or {0}
        result = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=30,
        )
        if result.returncode not in allowed:
            raise AgentTeamsSkillDeploymentError(
                f"Docker operation failed: {args[0]} {args[1] if len(args) > 1 else ''}".strip()
            )
        return result

    def inspect_container(self, container_name: str) -> dict[str, Any]:
        template = (
            '{"running":{{.State.Running}},"image":{{json .Config.Image}},'
            '"image_id":{{json .Image}}}'
        )
        result = self._run(["inspect", "--format", template, container_name])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AgentTeamsSkillDeploymentError(
                f"Docker returned invalid metadata for {container_name}"
            ) from exc
        return payload

    def path_exists(self, container_name: str, path: str) -> bool:
        result = self._run(
            ["exec", container_name, "test", "-e", path],
            allowed_returncodes={0, 1},
        )
        return result.returncode == 0

    def read_binding(self, container_name: str, skill_path: str) -> dict[str, Any] | None:
        binding_path = skill_path.rstrip("/") + "/LABOPS_RUNTIME_BINDING.json"
        if not self.path_exists(container_name, binding_path):
            return None
        result = self._run(["exec", container_name, "cat", binding_path])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AgentTeamsSkillDeploymentError(
                f"Runtime binding is invalid for {container_name}"
            ) from exc
        return payload

    def copy_skill(self, source: Path, container_name: str, skills_root: str) -> None:
        self._run(["cp", str(source), f"{container_name}:{skills_root.rstrip('/')}/"])

    def file_sha256(self, container_name: str, path: str) -> str | None:
        if not self.path_exists(container_name, path):
            return None
        result = self._run(["exec", container_name, "sha256sum", path])
        digest = result.stdout.strip().split(maxsplit=1)[0]
        return digest if len(digest) == 64 else None

    def list_skill_names(self, container_name: str) -> set[str]:
        result = self._run(["exec", container_name, "openclaw", "skills", "list", "--json"])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AgentTeamsSkillDeploymentError(
                f"OpenClaw returned invalid Skill inventory for {container_name}"
            ) from exc
        skills = payload.get("skills", [])
        return {
            item.get("name")
            for item in skills
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }


def _root(project_root: str | Path | None) -> Path:
    return Path(project_root) if project_root else Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentTeamsSkillDeploymentError(f"Cannot load {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AgentTeamsSkillDeploymentError(f"{path.name} must contain an object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_deployment_manifest(project_root: str | Path | None = None) -> dict[str, Any]:
    """Load and cross-check the runtime mapping against authoritative identities and Registry."""

    root = _root(project_root)
    manifest = _load_json(root / "config" / "agentteams-skill-deployment.json")
    try:
        validate_document(manifest, "agentteams_skill_deployment.schema.json", root)
    except ValueError as exc:
        raise AgentTeamsSkillDeploymentError(f"Deployment manifest rejected: {exc}") from exc

    runtime_lock = _load_json(root / "config" / "reviewer-runtime-lock.json")
    expected_version = runtime_lock.get("agentteams", {}).get("version")
    if manifest["agentteams_version"] != expected_version:
        raise AgentTeamsSkillDeploymentError("Deployment version differs from Reviewer runtime lock")

    identity_document = _load_json(root / "agentteams" / "agent_identities_v2.json")
    identities = {item["agent_id"]: item for item in identity_document.get("agents", [])}
    aliases = _load_json(root / "agentteams" / "worker_aliases.json").get("aliases", {})
    registry = {item["skill_id"]: item for item in list_skills(root)}

    deployed_skills: list[str] = []
    runtime_ids: set[str] = set()
    for deployment in manifest["deployments"]:
        runtime_id = deployment["runtime_agent_id"]
        canonical_id = deployment["canonical_agent_id"]
        if runtime_id in runtime_ids:
            raise AgentTeamsSkillDeploymentError(f"Duplicate runtime identity: {runtime_id}")
        runtime_ids.add(runtime_id)
        if canonical_id not in identities:
            raise AgentTeamsSkillDeploymentError(f"Unknown canonical identity: {canonical_id}")
        resolved_id = aliases.get(runtime_id, runtime_id)
        if resolved_id != canonical_id:
            raise AgentTeamsSkillDeploymentError(
                f"Runtime identity {runtime_id} does not resolve to {canonical_id}"
            )
        expected_skills = set(identities[canonical_id].get("skills", []))
        actual_skills = set(deployment["skill_ids"])
        if actual_skills != expected_skills:
            raise AgentTeamsSkillDeploymentError(
                f"Skill mapping differs from identity contract for {canonical_id}"
            )
        for skill_id in deployment["skill_ids"]:
            skill = registry.get(skill_id)
            if skill is None:
                raise AgentTeamsSkillDeploymentError(f"Unknown Skill in deployment: {skill_id}")
            if canonical_id not in skill["owner_agents"]:
                raise AgentTeamsSkillDeploymentError(
                    f"{canonical_id} is not authorized to own {skill_id}"
                )
            deployed_skills.append(skill_id)

    if len(deployed_skills) != len(set(deployed_skills)):
        raise AgentTeamsSkillDeploymentError("A Skill is assigned to more than one runtime identity")
    if set(deployed_skills) != set(registry):
        raise AgentTeamsSkillDeploymentError("Deployment must cover all and only active Skills")
    return manifest


def build_deployment_plan(project_root: str | Path | None = None) -> dict[str, Any]:
    """Return a deterministic, path-redacted plan without changing AgentTeams."""

    root = _root(project_root)
    manifest = load_deployment_manifest(root)
    registry = {item["skill_id"]: item for item in list_skills(root)}
    deployments = []
    for item in manifest["deployments"]:
        skills = []
        for skill_id in sorted(item["skill_ids"]):
            skill_dir = root / "skills" / skill_id
            skills.append(
                {
                    "skill_id": skill_id,
                    "version": registry[skill_id]["version"],
                    "owner_agent": item["canonical_agent_id"],
                    "skill_sha256": _sha256(skill_dir / "SKILL.md"),
                    "io_schema_sha256": _sha256(root / registry[skill_id]["io_schema"]),
                }
            )
        deployments.append(
            {
                "runtime_agent_id": item["runtime_agent_id"],
                "canonical_agent_id": item["canonical_agent_id"],
                "container_name": item["container_name"],
                "skills_root": item["skills_root"],
                "skills": skills,
            }
        )
    return {
        "schema_version": "1.0",
        "status": "READY",
        "mode": "PLAN_ONLY",
        "agentteams_version": manifest["agentteams_version"],
        "runtime_identity_count": len(deployments),
        "skill_count": sum(len(item["skills"]) for item in deployments),
        "deployments": deployments,
        "runtime_event_emission": "NOT_IMPLEMENTED",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def stage_skill_deployment(
    project_root: str | Path | None,
    destination: str | Path,
) -> dict[str, Any]:
    """Copy the existing Skill packages into a deterministic, non-runtime staging tree."""

    root = _root(project_root)
    target = Path(destination)
    if target.exists() and any(target.iterdir()):
        raise AgentTeamsSkillDeploymentError("Deployment staging destination is not empty")
    target.mkdir(parents=True, exist_ok=True)

    manifest_path = root / "config" / "agentteams-skill-deployment.json"
    manifest_sha256 = _sha256(manifest_path)
    plan = build_deployment_plan(root)
    for deployment in plan["deployments"]:
        runtime_root = target / deployment["runtime_agent_id"]
        runtime_root.mkdir(parents=True, exist_ok=True)
        for skill in deployment["skills"]:
            skill_id = skill["skill_id"]
            source = root / "skills" / skill_id
            staged = runtime_root / skill_id
            shutil.copytree(
                source,
                staged,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            binding = {
                "schema_version": "1.0",
                "agentteams_version": plan["agentteams_version"],
                "skill_id": skill_id,
                "skill_version": skill["version"],
                "canonical_owner_agent": deployment["canonical_agent_id"],
                "runtime_agent_id": deployment["runtime_agent_id"],
                "skill_sha256": skill["skill_sha256"],
                "io_schema_sha256": skill["io_schema_sha256"],
                "deployment_manifest_sha256": manifest_sha256,
                "runtime_event_emission": "NOT_IMPLEMENTED",
            }
            _write_json(staged / "LABOPS_RUNTIME_BINDING.json", binding)

    report = {
        **plan,
        "status": "STAGED",
        "mode": "STAGED_COPY",
        "persistence": "NOT_DEPLOYED",
    }
    _write_json(target / "deployment-plan.json", report)
    return report


def deploy_skill_packages(
    project_root: str | Path | None = None,
    *,
    confirm_version: str,
    runtime: Any | None = None,
) -> dict[str, Any]:
    """Deploy and verify real Skill discovery without claiming Skill invocation."""

    root = _root(project_root)
    plan = build_deployment_plan(root)
    if confirm_version != plan["agentteams_version"]:
        raise AgentTeamsSkillDeploymentError(
            f"Deployment requires explicit confirmation of {plan['agentteams_version']}"
        )
    runtime = runtime or DockerSkillRuntime()

    with tempfile.TemporaryDirectory(prefix="labops-agentteams-skills-") as temporary:
        stage_root = Path(temporary) / "stage"
        stage_skill_deployment(root, stage_root)
        pending: list[tuple[dict[str, Any], dict[str, Any], Path, str, dict[str, Any]]] = []
        container_metadata: dict[str, dict[str, Any]] = {}

        for deployment in plan["deployments"]:
            container = deployment["container_name"]
            metadata = runtime.inspect_container(container)
            if metadata.get("running") is not True:
                raise AgentTeamsSkillDeploymentError(f"AgentTeams container is not running: {container}")
            image = metadata.get("image")
            if not isinstance(image, str) or not image.endswith(f":{plan['agentteams_version']}"):
                raise AgentTeamsSkillDeploymentError(
                    f"AgentTeams image version mismatch for {container}"
                )
            container_metadata[container] = metadata
            for skill in deployment["skills"]:
                source = stage_root / deployment["runtime_agent_id"] / skill["skill_id"]
                destination = deployment["skills_root"].rstrip("/") + "/" + skill["skill_id"]
                expected_binding = json.loads(
                    (source / "LABOPS_RUNTIME_BINDING.json").read_text(encoding="utf-8")
                )
                if runtime.path_exists(container, destination):
                    if runtime.read_binding(container, destination) != expected_binding:
                        raise AgentTeamsSkillDeploymentError(
                            f"Runtime Skill conflict: {container}/{skill['skill_id']}"
                        )
                else:
                    pending.append((deployment, skill, source, destination, expected_binding))

        for deployment, _skill, source, _destination, _binding in pending:
            runtime.copy_skill(source, deployment["container_name"], deployment["skills_root"])

        results: list[dict[str, Any]] = []
        pending_keys = {
            (deployment["container_name"], skill["skill_id"])
            for deployment, skill, _source, _destination, _binding in pending
        }
        for deployment in plan["deployments"]:
            container = deployment["container_name"]
            discovered = runtime.list_skill_names(container)
            for skill in deployment["skills"]:
                skill_id = skill["skill_id"]
                source = stage_root / deployment["runtime_agent_id"] / skill_id
                destination = deployment["skills_root"].rstrip("/") + "/" + skill_id
                expected_binding = json.loads(
                    (source / "LABOPS_RUNTIME_BINDING.json").read_text(encoding="utf-8")
                )
                if runtime.read_binding(container, destination) != expected_binding:
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime binding verification failed: {container}/{skill_id}"
                    )
                observed_sha256 = runtime.file_sha256(container, destination + "/SKILL.md")
                if observed_sha256 != skill["skill_sha256"]:
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime Skill hash verification failed: {container}/{skill_id}"
                    )
                if skill_id not in discovered:
                    raise AgentTeamsSkillDeploymentError(
                        f"OpenClaw did not discover {skill_id} in {container}"
                    )
                results.append(
                    {
                        "skill_id": skill_id,
                        "skill_version": skill["version"],
                        "canonical_owner_agent": deployment["canonical_agent_id"],
                        "runtime_agent_id": deployment["runtime_agent_id"],
                        "container_name": container,
                        "container_image_id": container_metadata[container].get("image_id"),
                        "deployment": (
                            "DEPLOYED"
                            if (container, skill_id) in pending_keys
                            else "ALREADY_DEPLOYED"
                        ),
                        "discovery": "VERIFIED",
                        "binding": "VERIFIED",
                        "invocation": "UNVERIFIED",
                    }
                )

    return {
        "schema_version": "1.0",
        "status": "DEPLOYED",
        "agentteams_version": plan["agentteams_version"],
        "runtime_identity_count": plan["runtime_identity_count"],
        "skill_count": len(results),
        "skills": sorted(results, key=lambda item: item["skill_id"]),
        "runtime_event_emission": "NOT_IMPLEMENTED",
        "historical_evidence_modified": False,
    }


def verify_skill_packages(
    project_root: str | Path | None = None,
    *,
    runtime: Any | None = None,
) -> dict[str, Any]:
    """Read back runtime bindings, hashes, and OpenClaw discovery without writing anything."""

    root = _root(project_root)
    plan = build_deployment_plan(root)
    runtime = runtime or DockerSkillRuntime()
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="labops-agentteams-skills-verify-") as temporary:
        stage_root = Path(temporary) / "stage"
        stage_skill_deployment(root, stage_root)
        for deployment in plan["deployments"]:
            container = deployment["container_name"]
            metadata = runtime.inspect_container(container)
            if metadata.get("running") is not True:
                raise AgentTeamsSkillDeploymentError(f"AgentTeams container is not running: {container}")
            image = metadata.get("image")
            if not isinstance(image, str) or not image.endswith(f":{plan['agentteams_version']}"):
                raise AgentTeamsSkillDeploymentError(
                    f"AgentTeams image version mismatch for {container}"
                )
            discovered = runtime.list_skill_names(container)
            for skill in deployment["skills"]:
                skill_id = skill["skill_id"]
                source = stage_root / deployment["runtime_agent_id"] / skill_id
                destination = deployment["skills_root"].rstrip("/") + "/" + skill_id
                expected_binding = json.loads(
                    (source / "LABOPS_RUNTIME_BINDING.json").read_text(encoding="utf-8")
                )
                if not runtime.path_exists(container, destination):
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime Skill is missing: {container}/{skill_id}"
                    )
                if runtime.read_binding(container, destination) != expected_binding:
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime binding verification failed: {container}/{skill_id}"
                    )
                if runtime.file_sha256(container, destination + "/SKILL.md") != skill["skill_sha256"]:
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime Skill hash verification failed: {container}/{skill_id}"
                    )
                if skill_id not in discovered:
                    raise AgentTeamsSkillDeploymentError(
                        f"OpenClaw did not discover {skill_id} in {container}"
                    )
                results.append(
                    {
                        "skill_id": skill_id,
                        "skill_version": skill["version"],
                        "canonical_owner_agent": deployment["canonical_agent_id"],
                        "runtime_agent_id": deployment["runtime_agent_id"],
                        "container_name": container,
                        "container_image_id": metadata.get("image_id"),
                        "deployment": "OBSERVED",
                        "discovery": "VERIFIED",
                        "binding": "VERIFIED",
                        "invocation": "UNVERIFIED",
                    }
                )

    return {
        "schema_version": "1.0",
        "status": "VERIFIED",
        "agentteams_version": plan["agentteams_version"],
        "runtime_identity_count": plan["runtime_identity_count"],
        "skill_count": len(results),
        "skills": sorted(results, key=lambda item: item["skill_id"]),
        "runtime_event_emission": "NOT_IMPLEMENTED",
        "historical_evidence_modified": False,
    }
