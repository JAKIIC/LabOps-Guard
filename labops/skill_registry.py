"""Read-only registry for repository-native LabOps Guard Skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from labops.contracts import validate_document


class SkillRegistryError(ValueError):
    """Raised when the registry cannot be trusted."""


class SkillNotFoundError(SkillRegistryError):
    """Raised when a requested Skill is not registered."""


class SkillAuthorizationError(PermissionError):
    """Raised when an Agent is outside a Skill owner boundary."""


class SkillInputError(SkillRegistryError):
    """Raised when a Skill invocation lacks required context."""


REQUIRED_SKILL_FIELDS = {
    "skill_id",
    "version",
    "owner_agents",
    "io_schema",
    "tool_dependencies",
    "invocation_condition",
    "policy_class",
    "failure_states",
    "audit_events",
    "lifecycle",
}

KNOWN_TOOL_DEPENDENCIES = {
    "allowlisted-filesystem",
    "sha256",
    "evidence-store",
    "policy-engine",
    "runner-gateway",
    "sandbox-runner",
    "runner-artifacts",
    "trace-verifier",
    "artifact-store",
    "case-memory-store",
}


def _root(project_root: str | Path | None) -> Path:
    return Path(project_root) if project_root else Path(__file__).resolve().parent.parent


def _load_registry(project_root: str | Path | None = None) -> dict[str, Any]:
    root = _root(project_root)
    path = root / "skills" / "registry.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_document(payload, "skill_registry.schema.json", root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SkillRegistryError(f"Skill Registry rejected: {exc}") from exc
    skills = payload.get("skills")
    if not isinstance(skills, list) or not skills:
        raise SkillRegistryError("Skill Registry rejected: skills must be a non-empty list")
    seen: set[str] = set()
    for skill in skills:
        if not isinstance(skill, dict) or not REQUIRED_SKILL_FIELDS.issubset(skill):
            raise SkillRegistryError("Skill Registry rejected: incomplete skill entry")
        skill_id = skill["skill_id"]
        if skill_id in seen:
            raise SkillRegistryError(f"Skill Registry rejected: duplicate {skill_id}")
        seen.add(skill_id)
        schema_path = root / skill["io_schema"]
        if not schema_path.is_file():
            raise SkillRegistryError(f"Skill Registry rejected: missing {skill['io_schema']}")
        unknown_tools = sorted(set(skill["tool_dependencies"]) - KNOWN_TOOL_DEPENDENCIES)
        if unknown_tools:
            raise SkillRegistryError(
                f"Skill Registry rejected: unknown tool dependencies for {skill_id}: "
                + ", ".join(unknown_tools)
            )
        try:
            io_contract = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillRegistryError(
                f"Skill Registry rejected: unreadable I/O contract for {skill_id}: {exc}"
            ) from exc
        if io_contract.get("skill_version") != skill["version"]:
            raise SkillRegistryError(
                f"Skill Registry rejected: version mismatch for {skill_id}"
            )
        if not (root / "skills" / skill_id / "SKILL.md").is_file():
            raise SkillRegistryError(f"Skill Registry rejected: missing SKILL.md for {skill_id}")
    return payload


def list_skills(project_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Return active Skills in deterministic ID order."""

    skills = _load_registry(project_root)["skills"]
    return sorted(
        (dict(skill) for skill in skills if skill["lifecycle"] == "active"),
        key=lambda item: item["skill_id"],
    )


def describe_skill(
    skill_id: str,
    project_root: str | Path | None = None,
    caller_agent_id: str | None = None,
) -> dict[str, Any]:
    """Return one Skill and enforce the optional caller boundary."""

    skill = next((item for item in list_skills(project_root) if item["skill_id"] == skill_id), None)
    if skill is None:
        raise SkillNotFoundError(f"Skill not registered: {skill_id}")
    if caller_agent_id is not None and caller_agent_id not in skill["owner_agents"]:
        raise SkillAuthorizationError(
            f"{caller_agent_id} is not authorized to invoke {skill_id}"
        )
    return skill


def validate_skill_input(
    skill_id: str,
    document: dict[str, Any],
    project_root: str | Path | None = None,
    caller_agent_id: str | None = None,
) -> dict[str, Any]:
    """Validate required invocation fields from the Skill I/O contract."""

    if not isinstance(document, dict):
        raise SkillInputError("Skill input must be an object")
    root = _root(project_root)
    skill = describe_skill(skill_id, root, caller_agent_id)
    io_contract = json.loads((root / skill["io_schema"]).read_text(encoding="utf-8"))
    required = set(io_contract.get("input", {}).get("required", []))
    if skill["policy_class"] == "manual_approval":
        if "approval" not in document and "approval_id" not in document:
            required.add("approval")
    missing = sorted(name for name in required if name not in document)
    if missing:
        raise SkillInputError(f"Missing required Skill input: {', '.join(missing)}")
    return {"valid": True, "skill_id": skill_id, "version": skill["version"]}


def validate_skill_output(
    skill_id: str,
    document: dict[str, Any],
    project_root: str | Path | None = None,
    caller_agent_id: str | None = None,
) -> dict[str, Any]:
    """Validate the required output fields declared by a Skill I/O contract."""

    if not isinstance(document, dict):
        raise SkillInputError("Skill output must be an object")
    root = _root(project_root)
    skill = describe_skill(skill_id, root, caller_agent_id)
    io_contract = json.loads((root / skill["io_schema"]).read_text(encoding="utf-8"))
    required = set(io_contract.get("output", {}).get("required", []))
    missing = sorted(name for name in required if name not in document)
    if missing:
        raise SkillInputError(f"Missing required Skill output: {', '.join(missing)}")
    return {"valid": True, "skill_id": skill_id, "version": skill["version"]}


def validate_skill_usage_event(
    document: dict[str, Any],
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a real live-run Skill event without creating or persisting it."""

    if not isinstance(document, dict):
        raise SkillInputError("Skill usage event must be an object")
    root = _root(project_root)
    try:
        validate_document(document, "skill_usage_event.schema.json", root)
    except ValueError as exc:
        raise SkillInputError(f"Invalid Skill usage event: {exc}") from exc
    skill = describe_skill(
        document["skill_id"], root, caller_agent_id=document["owner_agent"]
    )
    io_contract = json.loads((root / skill["io_schema"]).read_text(encoding="utf-8"))
    schema_version = io_contract.get("schema_version")
    if document["skill_version"] != skill["version"]:
        raise SkillInputError("Skill usage event version differs from the active Registry")
    if document["input_schema_version"] != schema_version or document["output_schema_version"] != schema_version:
        raise SkillInputError("Skill usage event I/O schema version differs from the active contract")
    terminal = document["status"] in {"COMPLETED", "BLOCKED", "FAILED"}
    if terminal and not document["completed_at"]:
        raise SkillInputError("Terminal Skill usage event requires completed_at")
    if document["status"] == "STARTED" and document["completed_at"] is not None:
        raise SkillInputError("STARTED Skill usage event must not claim completed_at")
    if document["status"] == "COMPLETED" and not document["output_artifact_refs"]:
        raise SkillInputError("COMPLETED Skill usage event requires output artifact references")
    if document["completed_at"] and document["completed_at"] < document["started_at"]:
        raise SkillInputError("Skill usage event completed_at precedes started_at")
    return {
        "status": "VALID",
        "skill_id": skill["skill_id"],
        "skill_version": skill["version"],
        "owner_agent": document["owner_agent"],
        "persistence": "NOT_PERFORMED",
    }
