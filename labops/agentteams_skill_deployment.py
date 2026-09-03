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
from labops.matrix_observer import load_room_map
from labops.skill_registry import list_skills


class AgentTeamsSkillDeploymentError(ValueError):
    """Raised when the runtime Skill mapping cannot be trusted."""


EVENT_ROUTES = {
    "labops-manager": {
        "manager_to_collector": ("evidence-collector", "evidence-collector"),
        "commander_published": ("labops-manager", "labops-manager"),
    },
    "evidence-collector": {
        "collector_to_rca": ("evidence-collector", "labops-manager"),
        "evidence_incomplete": ("evidence-collector", "labops-manager"),
    },
    "rca-analyst": {
        "rca_to_planner": ("rca-analyst", "labops-manager"),
    },
    "experiment-planner": {
        "approval_pending": ("experiment-planner", "labops-manager"),
    },
    "safe-executor": {
        "executor_to_gateway": ("safe-executor", "labops-manager"),
        "runner_started": ("safe-executor", "labops-manager"),
        "runner_completed": ("safe-executor", "labops-manager"),
        "executor_to_auditor": ("safe-executor", "labops-manager"),
    },
    "verification-auditor": {
        "verification_completed": ("verification-auditor", "labops-manager"),
        "terminal_decided": ("verification-auditor", "labops-manager"),
    },
}

MATRIX_LOCALPARTS = {
    "labops-manager": "manager",
    "evidence-collector": "evidence-collector",
    "rca-analyst": "rca-analyst",
    "experiment-planner": "researcher",
    "safe-executor": "controlled-executor",
    "verification-auditor": "verification-auditor",
}


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
        return self.read_json(container_name, binding_path)

    def read_json(self, container_name: str, path: str) -> dict[str, Any] | None:
        if not self.path_exists(container_name, path):
            return None
        result = self._run(["exec", container_name, "cat", path])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AgentTeamsSkillDeploymentError(
                f"Runtime JSON is invalid for {container_name}"
            ) from exc
        if not isinstance(payload, dict):
            raise AgentTeamsSkillDeploymentError(
                f"Runtime JSON is not an object for {container_name}"
            )
        return payload

    def copy_skill(self, source: Path, container_name: str, skills_root: str) -> None:
        self._run(["cp", str(source), f"{container_name}:{skills_root.rstrip('/')}/"])

    def replace_skill(self, source: Path, container_name: str, destination: str) -> str:
        """Stage, back up, and atomically swap one fixed Skill directory."""

        destination = destination.rstrip("/")
        skills_root, skill_id = destination.rsplit("/", 1)
        new_hash = _sha256(source / "LABOPS_RUNTIME_BINDING.json")[:12]
        old_hash = self.file_sha256(
            container_name, destination + "/LABOPS_RUNTIME_BINDING.json"
        )
        old_label = (old_hash or "unbound")[:12]
        stage = f"{skills_root}/.labops-stage-{skill_id}-{new_hash}"
        backup = f"{destination}.labops-backup-{old_label}"
        if self.path_exists(container_name, stage) or self.path_exists(container_name, backup):
            raise AgentTeamsSkillDeploymentError(
                f"Safe replacement path already exists for {container_name}/{skill_id}"
            )
        self._run(["cp", str(source), f"{container_name}:{stage}"])
        try:
            self._run(["exec", container_name, "mv", destination, backup])
            try:
                self._run(["exec", container_name, "mv", stage, destination])
            except AgentTeamsSkillDeploymentError:
                self._run(["exec", container_name, "mv", backup, destination])
                raise
        except AgentTeamsSkillDeploymentError:
            raise
        return backup

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

    def dry_run_emitter(self, container_name: str, skill_path: str) -> bool:
        """Execute the deployed emitter without sending a Matrix message."""

        skill_path = skill_path.rstrip("/")
        binding_path = skill_path + "/LABOPS_HANDOFF_RUNTIME.json"
        binding = self.read_json(container_name, binding_path)
        events = binding.get("events") if isinstance(binding, dict) else None
        if not isinstance(events, dict) or not events:
            return False
        event_kind = sorted(events)[0]
        result = self._run(
            [
                "exec",
                container_name,
                "python3",
                skill_path + "/scripts/emit_handoff.py",
                "--binding",
                binding_path,
                "--session-root",
                "/nonexistent/labops-emitter-dry-run",
                "--session-id",
                "20991231-999",
                "--task-instance-id",
                "LIVE-TASK-20991231-999",
                "--incident-instance-id",
                "LIVE-INCIDENT-20991231-999",
                "--attempt-id",
                "LIVE-ATTEMPT-20991231-999-01",
                "--run-id",
                "RUN-LABOPS-AT-004-AGENTTEAMS-999",
                "--event-kind",
                event_kind,
                "--input-artifact",
                "dry-run/input.json",
                "--output-artifact",
                "dry-run/output.json",
                "--dry-run",
            ]
        )
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError, UnicodeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("status") == "DRY_RUN"
            and payload.get("event_kind") == event_kind
            and payload.get("session_id") == "20991231-999"
            and "event_id" not in payload
        )


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


def _room_roles(room_map_path: str | Path) -> dict[str, str]:
    try:
        room_to_role = load_room_map(room_map_path)
    except (OSError, ValueError) as exc:
        raise AgentTeamsSkillDeploymentError(f"Room binding rejected: {exc}") from exc
    role_to_room = {role: room_id for room_id, role in room_to_role.items()}
    missing = sorted(set(EVENT_ROUTES) - set(role_to_room))
    if missing:
        raise AgentTeamsSkillDeploymentError(
            "Room binding lacks required Agent roles: " + ", ".join(missing)
        )
    return role_to_room


def _matrix_user(agent_id: str, room_roles: dict[str, str]) -> str:
    room_id = room_roles[agent_id]
    domain = room_id.split(":", 1)[1]
    return f"@{MATRIX_LOCALPARTS[agent_id]}:{domain}"


def build_handoff_runtime_binding(
    deployment: dict[str, Any],
    skill_id: str,
    room_roles: dict[str, str],
) -> dict[str, Any]:
    """Build one credential-free, role-bound event routing sidecar."""

    canonical = deployment["canonical_agent_id"]
    routes = EVENT_ROUTES.get(canonical)
    if routes is None:
        raise AgentTeamsSkillDeploymentError(
            f"No handoff event contract exists for {canonical}"
        )
    events = {
        event_kind: {
            "room_id": room_roles[room_role],
            "recipient_matrix_id": _matrix_user(recipient_role, room_roles),
        }
        for event_kind, (room_role, recipient_role) in sorted(routes.items())
    }
    return {
        "schema_version": "1.0",
        "skill_id": skill_id,
        "canonical_agent_id": canonical,
        "runtime_agent_id": deployment["runtime_agent_id"],
        "matrix_room_id": room_roles[canonical],
        "coordinator_matrix_id": _matrix_user("labops-manager", room_roles),
        "allowed_event_kinds": sorted(events),
        "events": events,
    }


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
        "runtime_event_emission": "REQUIRES_ROOM_BOUND_DEPLOYMENT",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def stage_skill_deployment(
    project_root: str | Path | None,
    destination: str | Path,
    *,
    room_map_path: str | Path,
) -> dict[str, Any]:
    """Copy the existing Skill packages into a deterministic, non-runtime staging tree."""

    root = _root(project_root)
    target = Path(destination)
    if target.exists() and any(target.iterdir()):
        raise AgentTeamsSkillDeploymentError("Deployment staging destination is not empty")
    target.mkdir(parents=True, exist_ok=True)

    manifest_path = root / "config" / "agentteams-skill-deployment.json"
    manifest_sha256 = _sha256(manifest_path)
    emitter_source = root / "labops" / "handoff_emitter.py"
    emitter_sha256 = _sha256(emitter_source)
    room_roles = _room_roles(room_map_path)
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
            scripts = staged / "scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            shutil.copy2(emitter_source, scripts / "emit_handoff.py")
            handoff_binding = build_handoff_runtime_binding(
                deployment, skill_id, room_roles
            )
            _write_json(staged / "LABOPS_HANDOFF_RUNTIME.json", handoff_binding)
            handoff_binding_sha256 = _sha256(
                staged / "LABOPS_HANDOFF_RUNTIME.json"
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
                "handoff_emitter_sha256": emitter_sha256,
                "handoff_runtime_sha256": handoff_binding_sha256,
                "runtime_event_emission": "VERIFIED",
            }
            _write_json(staged / "LABOPS_RUNTIME_BINDING.json", binding)

    report = {
        **plan,
        "status": "STAGED",
        "mode": "STAGED_COPY",
        "persistence": "NOT_DEPLOYED",
        "runtime_event_emission": "VERIFIED",
        "handoff_emitter_sha256": emitter_sha256,
    }
    _write_json(target / "deployment-plan.json", report)
    return report


def _staged_contract(source: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _load_json(source / "LABOPS_RUNTIME_BINDING.json"),
        _load_json(source / "LABOPS_HANDOFF_RUNTIME.json"),
    )


def _runtime_package_matches(
    runtime: Any,
    container: str,
    destination: str,
    source: Path,
    expected_skill_sha256: str,
) -> bool:
    binding, handoff = _staged_contract(source)
    checks = (
        runtime.read_binding(container, destination) == binding,
        runtime.read_json(
            container, destination + "/LABOPS_HANDOFF_RUNTIME.json"
        )
        == handoff,
        runtime.file_sha256(container, destination + "/SKILL.md")
        == expected_skill_sha256,
        runtime.file_sha256(container, destination + "/scripts/emit_handoff.py")
        == binding["handoff_emitter_sha256"],
        runtime.file_sha256(
            container, destination + "/LABOPS_HANDOFF_RUNTIME.json"
        )
        == binding["handoff_runtime_sha256"],
    )
    return all(checks)


def deploy_skill_packages(
    project_root: str | Path | None = None,
    *,
    confirm_version: str,
    room_map_path: str | Path,
    replace_existing: bool = False,
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
        stage_skill_deployment(root, stage_root, room_map_path=room_map_path)
        pending: list[tuple[dict[str, Any], dict[str, Any], Path, str, str]] = []
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
                if runtime.path_exists(container, destination):
                    if not _runtime_package_matches(
                        runtime, container, destination, source, skill["skill_sha256"]
                    ):
                        if not replace_existing:
                            raise AgentTeamsSkillDeploymentError(
                                f"Runtime Skill conflict: {container}/{skill['skill_id']}"
                            )
                        pending.append(
                            (deployment, skill, source, destination, "REPLACED")
                        )
                else:
                    pending.append((deployment, skill, source, destination, "DEPLOYED"))

        actions: dict[tuple[str, str], str] = {}
        backups: dict[tuple[str, str], str] = {}
        for deployment, skill, source, destination, action_name in pending:
            container = deployment["container_name"]
            key = (container, skill["skill_id"])
            if action_name == "REPLACED":
                runtime.replace_skill(source, container, destination)
                backups[key] = "CREATED"
            else:
                runtime.copy_skill(source, container, deployment["skills_root"])
            actions[key] = action_name

        results: list[dict[str, Any]] = []
        for deployment in plan["deployments"]:
            container = deployment["container_name"]
            discovered = runtime.list_skill_names(container)
            for skill in deployment["skills"]:
                skill_id = skill["skill_id"]
                source = stage_root / deployment["runtime_agent_id"] / skill_id
                destination = deployment["skills_root"].rstrip("/") + "/" + skill_id
                if not _runtime_package_matches(
                    runtime, container, destination, source, skill["skill_sha256"]
                ):
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime package verification failed: {container}/{skill_id}"
                    )
                if skill_id not in discovered:
                    raise AgentTeamsSkillDeploymentError(
                        f"OpenClaw did not discover {skill_id} in {container}"
                    )
                if not runtime.dry_run_emitter(container, destination):
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime emitter dry-run failed: {container}/{skill_id}"
                    )
                results.append(
                    {
                        "skill_id": skill_id,
                        "skill_version": skill["version"],
                        "canonical_owner_agent": deployment["canonical_agent_id"],
                        "runtime_agent_id": deployment["runtime_agent_id"],
                        "container_name": container,
                        "container_image_id": container_metadata[container].get("image_id"),
                        "deployment": actions.get(
                            (container, skill_id), "ALREADY_DEPLOYED"
                        ),
                        "backup": backups.get(
                            (container, skill_id), "NOT_APPLICABLE"
                        ),
                        "discovery": "VERIFIED",
                        "binding": "VERIFIED",
                        "event_emitter": "VERIFIED",
                        "emitter_dry_run": "VERIFIED",
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
        "runtime_event_emission": "VERIFIED",
        "historical_evidence_modified": False,
    }


def verify_skill_packages(
    project_root: str | Path | None = None,
    *,
    room_map_path: str | Path,
    runtime: Any | None = None,
) -> dict[str, Any]:
    """Read back runtime bindings, hashes, and OpenClaw discovery without writing anything."""

    root = _root(project_root)
    plan = build_deployment_plan(root)
    runtime = runtime or DockerSkillRuntime()
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="labops-agentteams-skills-verify-") as temporary:
        stage_root = Path(temporary) / "stage"
        stage_skill_deployment(root, stage_root, room_map_path=room_map_path)
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
                if not runtime.path_exists(container, destination):
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime Skill is missing: {container}/{skill_id}"
                    )
                if not _runtime_package_matches(
                    runtime, container, destination, source, skill["skill_sha256"]
                ):
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime package verification failed: {container}/{skill_id}"
                    )
                if skill_id not in discovered:
                    raise AgentTeamsSkillDeploymentError(
                        f"OpenClaw did not discover {skill_id} in {container}"
                    )
                if not runtime.dry_run_emitter(container, destination):
                    raise AgentTeamsSkillDeploymentError(
                        f"Runtime emitter dry-run failed: {container}/{skill_id}"
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
                        "event_emitter": "VERIFIED",
                        "emitter_dry_run": "VERIFIED",
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
        "runtime_event_emission": "VERIFIED",
        "historical_evidence_modified": False,
    }
