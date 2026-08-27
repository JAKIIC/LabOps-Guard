"""Short-lived, allowlisted control plane for AgentTeams Safe Executor.

The gateway is not an experiment runtime and is not an Agent. It accepts only
one allowlisted task contract and starts the network-disabled Runner through
the host Docker adapter. It should be stopped after the AgentTeams run.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from labops.approval_grant import (
    ApprovalBindingError,
    consume_approval_nonce,
    validate_approval_grant,
)
from labops.contracts import validate_document
from labops.runner import AT004_RUNNER_IMAGE, RUNNER_IMAGE, execute_runner_plan


MAX_BODY = 64 * 1024
RUN_ID = re.compile(r"^RUN-LABOPS-AT-003-AGENTTEAMS-[0-9]{3}$")
RUN_ID_AT004 = re.compile(r"^RUN-LABOPS-AT-004-AGENTTEAMS-[0-9]{3}$")
TASK_CONTRACTS = {
    "LABOPS-AT-003": {
        "incident_id": "DEMO-RCA-003",
        "image": RUNNER_IMAGE,
        "run_id": RUN_ID,
        "demo": ("demos", "checkpoint-regression"),
        "baseline": ("artifacts", "DEMO-RCA-001", "baseline", "run-01"),
    },
    "LABOPS-AT-004-EVAL-DRIFT": {
        "incident_id": "DEMO-EVAL-DRIFT-004",
        "image": AT004_RUNNER_IMAGE,
        "run_id": RUN_ID_AT004,
        "demo": ("demos", "eval-drift"),
        "baseline": ("demos", "eval-drift", "fixture", "run-01"),
    },
}

ERROR_CODES = {
    "INVALID_SCHEMA",
    "UNAUTHORIZED_AGENT",
    "APPROVAL_REQUIRED",
    "POLICY_DENIED",
    "TASK_NOT_ALLOWLISTED",
    "RUN_ID_CONFLICT",
    "RUNNER_TIMEOUT",
    "EVIDENCE_INCOMPLETE",
    "VERIFICATION_FAILED",
}


def normalize_tool_contract(request: dict) -> dict:
    """Return the governed Tool Contract for new or legacy Gateway requests.

    Legacy AgentTeams payloads remain accepted.  The Gateway derives the
    missing trust metadata from their fixed plan and approval contract, then
    archives the normalized contract with the request.
    """

    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    plan = request.get("experiment_plan")
    approval = request.get("approval")
    if not isinstance(plan, dict) or not isinstance(approval, dict):
        raise ValueError("structured experiment_plan and approval required")
    supplied = request.get("tool_contract")
    if supplied is not None and not isinstance(supplied, dict):
        raise ValueError("tool_contract must be an object")
    supplied = supplied or {}
    run_id = str(plan.get("run_id", ""))
    contract = {
        "tool_id": supplied.get("tool_id", "labops.runner.execute"),
        "caller_agent_id": supplied.get("caller_agent_id", "safe-executor"),
        "skill_id": supplied.get("skill_id", "control-lab-action"),
        "task_id": supplied.get("task_id", str(plan.get("task_id", ""))),
        "incident_id": supplied.get("incident_id", str(plan.get("incident_id", ""))),
        "run_id": supplied.get("run_id", run_id),
        "approval_reference": supplied.get("approval_reference", str(approval.get("approval_id", ""))),
        "input_schema_version": supplied.get("input_schema_version", "1.0"),
        "allowed_side_effects": supplied.get("allowed_side_effects", ["write sandbox output"]),
        "protected_resources": supplied.get(
            "protected_resources",
            list(plan.get("forbidden_changes", [])),
        ),
        "resource_budget": supplied.get("resource_budget", dict(plan.get("budget", {}))),
        "idempotency_key": supplied.get("idempotency_key", run_id),
        "success_postconditions": supplied.get(
            "success_postconditions", dict(plan.get("success_criteria", {}))
        ),
        "audit_context": supplied.get(
            "audit_context",
            {"approval_id": approval.get("approval_id"), "decided_by": approval.get("decided_by")},
        ),
    }
    required_strings = (
        "tool_id",
        "caller_agent_id",
        "skill_id",
        "task_id",
        "incident_id",
        "run_id",
        "approval_reference",
        "input_schema_version",
        "idempotency_key",
    )
    if any(not isinstance(contract[name], str) or not contract[name] for name in required_strings):
        raise ValueError("tool contract identifiers must be non-empty strings")
    if contract["caller_agent_id"] != "safe-executor":
        raise PermissionError("only safe-executor may invoke the Runner Gateway")
    if contract["skill_id"] != "control-lab-action":
        raise PermissionError("Runner Gateway requires control-lab-action")
    bindings = {
        "task_id": str(plan.get("task_id", "")),
        "incident_id": str(plan.get("incident_id", "")),
        "run_id": run_id,
        "approval_reference": str(approval.get("approval_id", "")),
    }
    if any(contract[name] != value for name, value in bindings.items()):
        raise ValueError("tool contract identity binding does not match plan and approval")
    validate_document(contract, "tool_contract.schema.json")
    return contract


def _read_outputs(run_dir: Path) -> dict:
    return {
        "run_result.json": json.loads((run_dir / "run_result.json").read_text(encoding="utf-8")),
        "metrics.json": json.loads((run_dir / "metrics.json").read_text(encoding="utf-8")),
        "stdout.log": (run_dir / "stdout.log").read_text(encoding="utf-8"),
        "stderr.log": (run_dir / "stderr.log").read_text(encoding="utf-8"),
        "artifact_manifest.json": json.loads((run_dir / "artifact_manifest.json").read_text(encoding="utf-8")),
    }


def make_handler(repo_root: Path, output_root: Path):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "LabOpsRunnerGateway/0.2.0"

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _error(
            self,
            status: int,
            code: str,
            message: str,
            detail: str | None = None,
            reason: str | None = None,
        ) -> None:
            if code not in ERROR_CODES:
                raise ValueError(f"unknown Gateway error code: {code}")
            payload = {"ok": False, "code": code, "error": message}
            if reason:
                payload["reason"] = reason
            if detail:
                payload["detail"] = detail[:500]
            self._send(status, payload)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {
                    "ok": True,
                    "service": "labops-runner-gateway",
                    "runner_images": [RUNNER_IMAGE, AT004_RUNNER_IMAGE],
                    "task_contracts": sorted(TASK_CONTRACTS),
                })
            else:
                self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/run":
                self._send(404, {"ok": False, "error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self._error(413, "INVALID_SCHEMA", "invalid request size")
                return
            try:
                request = json.loads(self.rfile.read(length))
                plan = request["experiment_plan"]
                approval = request["approval"]
            except (KeyError, json.JSONDecodeError, TypeError):
                self._error(400, "INVALID_SCHEMA", "structured experiment_plan and approval required")
                return
            if not isinstance(plan, dict) or not isinstance(approval, dict):
                self._error(400, "INVALID_SCHEMA", "structured experiment_plan and approval required")
                return
            try:
                tool_contract = normalize_tool_contract(request)
            except PermissionError as exc:
                self._error(403, "UNAUTHORIZED_AGENT", str(exc))
                return
            except ValueError as exc:
                self._error(400, "INVALID_SCHEMA", str(exc))
                return
            try:
                approval_binding = validate_approval_grant(plan, approval, tool_contract)
            except ApprovalBindingError as exc:
                self._error(
                    403,
                    "APPROVAL_REQUIRED",
                    "ApprovalGrant v1 does not authorize this execution",
                    exc.detail,
                    exc.reason,
                )
                return
            task_id = str(plan.get("task_id", ""))
            contract = TASK_CONTRACTS.get(task_id)
            run_id = str(plan.get("run_id", ""))
            allowed = (
                contract is not None
                and plan.get("incident_id") == contract["incident_id"]
                and contract["run_id"].fullmatch(run_id) is not None
                and plan.get("runtime", {}).get("image") == contract["image"]
                and approval.get("task_id") == task_id
                and approval.get("decision") == "APPROVED"
                and bool(approval.get("approval_id"))
                and bool(approval.get("decided_by"))
                and bool(approval.get("approved_at"))
            )
            if not allowed:
                code = "APPROVAL_REQUIRED" if approval.get("decision") != "APPROVED" else "TASK_NOT_ALLOWLISTED"
                self._error(403, code, "task, runner, run_id or human approval is outside the fixed contract")
                return
            if not lock.acquire(blocking=False):
                self._error(409, "RUN_ID_CONFLICT", "runner busy")
                return
            try:
                run_dir = output_root / run_id
                if run_dir.exists():
                    self._error(409, "RUN_ID_CONFLICT", "run_id already exists; evidence is append-only")
                    return
                try:
                    approval_consumption = consume_approval_nonce(
                        approval,
                        output_root / "approval_nonce_ledger.json",
                    )
                except ApprovalBindingError as exc:
                    self._error(
                        403,
                        "APPROVAL_REQUIRED",
                        "ApprovalGrant v1 does not authorize this execution",
                        exc.detail,
                        exc.reason,
                    )
                    return
                run_dir.mkdir(parents=True, exist_ok=False)
                request["tool_contract"] = tool_contract
                request["approval_binding"] = approval_binding
                request["approval_consumption"] = approval_consumption
                (run_dir / "gateway_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                demo = repo_root.joinpath(*contract["demo"])
                baseline = repo_root.joinpath(*contract["baseline"])
                result = execute_runner_plan(plan, demo, baseline, run_dir, contract["image"])
                response = {
                    "ok": result.get("status") == "completed",
                    "task_id": task_id,
                    "run_id": run_id,
                    "approval_id": approval["approval_id"],
                    "control_plane": "short-lived local gateway",
                    "experiment_network": "none",
                    "runner_image": contract["image"],
                    "tool_contract": tool_contract,
                    "artifacts": _read_outputs(run_dir),
                }
                (run_dir / "gateway_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
                self._send(200 if response["ok"] else 422, response)
            except TimeoutError as exc:
                self._error(504, "RUNNER_TIMEOUT", "Runner timed out", str(exc))
            except Exception as exc:
                self._error(500, "VERIFICATION_FAILED", type(exc).__name__, str(exc))
            finally:
                lock.release()

        def log_message(self, fmt: str, *args) -> None:
            print(f"[runner-gateway] {self.client_address[0]} {fmt % args}", flush=True)

    return Handler


def serve(repo_root: str | Path, output_root: str | Path, host: str = "127.0.0.1", port: int = 18103) -> None:
    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), make_handler(repo_root, output_root))
    print(f"LabOps Runner Gateway: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18103)
    args = parser.parse_args()
    serve(args.repo_root, args.output_root, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
