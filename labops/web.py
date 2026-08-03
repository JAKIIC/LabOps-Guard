"""Local-only dashboard for LabOps Guard.

The server uses only Python's standard library and exposes read-only demo state.
It never serves arbitrary files from the workspace and never reads excluded data.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from labops.trace import TraceLog


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _counts(records: list[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        value = str(record.get(key, "UNKNOWN"))
        result[value] = result.get(value, 0) + 1
    return result


def build_dashboard_state(workspace: str | Path) -> dict:
    """Build the allowlisted dashboard payload from generated demo artifacts."""
    workspace = Path(workspace)
    summary = _read_json(workspace / "demo" / "demo_summary.json", {})
    manifest = _read_json(workspace / "evidence_bundle_manifest.json", {})
    registry = _read_json(workspace / "registry_record.json", {})
    collected = _read_json(workspace / "collected_evidence.json", {})
    diagnosis = _read_json(workspace / "diagnosis_candidates.json", {})
    approvals = _read_json(workspace / "approval_requests.json", [])
    execution = _read_json(workspace / "execution_result.json", {})
    verification = _read_json(workspace / "verification_result.json", {})

    trace = TraceLog(workspace / "trace.jsonl")
    try:
        trace_records = trace.read()
        trace_ok, trace_message = trace.verify_chain()
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        trace_records = []
        trace_ok, trace_message = False, f"trace unreadable: {exc}"

    hypotheses = diagnosis.get("hypotheses", [])
    evidence = collected.get("evidence", [])
    gaps = collected.get("gaps", [])
    is_agentteams = bool(manifest.get("task_id") and manifest.get("participating_agents"))
    ready = bool(registry and collected and diagnosis and verification and (summary or is_agentteams))
    approval_counts = _counts(approvals, "status")
    action_events = [r for r in trace_records if r.get("entity_type") == "action"]
    manifest_counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    manifest_verification = manifest.get("verification", {}) if isinstance(manifest.get("verification"), dict) else {}
    execution_result = execution.get("result", {}) if isinstance(execution.get("result"), dict) else {}

    agent_roles = {
        "labops-manager": "编排、状态治理与证据打包",
        "evidence-collector": "白名单证据采集",
        "rca-analyst": "证据约束 RCA",
        "controlled-executor": "审批门禁与受控执行",
        "verification-auditor": "独立验证与闭环裁决",
    }
    participating_agents = manifest.get("participating_agents", []) if is_agentteams else []
    agents = [
        {"id": agent_id, "role": agent_roles.get(agent_id, "受控协作角色"), "status": "COMPLETED"}
        for agent_id in participating_agents
    ]
    handoffs = []
    if is_agentteams:
        handoffs = [
            {"from": "labops-manager", "to": "evidence-collector", "result": "EVIDENCE_READY"},
            {"from": "evidence-collector", "to": "rca-analyst", "result": "DIAGNOSIS_READY"},
            {"from": "rca-analyst", "to": "controlled-executor", "result": "SIMULATED_SUCCEEDED"},
            {"from": "controlled-executor", "to": "verification-auditor", "result": "DEMO_PASSED_NOT_RESOLVED"},
            {"from": "verification-auditor", "to": "labops-manager", "result": "EVIDENCE_PACKAGED"},
        ][: int(manifest.get("handoff_count", 0))]

    allowed_files = summary.get("allowed_files", manifest_counts.get("allowed_files", registry.get("allowed_file_count", 0)))
    evidence_count = summary.get("evidence_count", manifest_counts.get("evidence", collected.get("evidence_count", 0)))
    gaps_count = summary.get("gaps_count", manifest_counts.get("gaps", collected.get("gaps_count", 0)))
    demo_verification = summary.get("demo_verification", manifest_verification.get("demo_verification", verification.get("demo_verification", "NOT_RUN")))
    incident_state = summary.get("incident_state", manifest.get("final_state", verification.get("incident_state", "NOT_RUN")))
    underlying_issue_resolved = bool(summary.get("underlying_issue_resolved", manifest_verification.get("underlying_issue_resolved", verification.get("underlying_issue_resolved", False))))

    return {
        "schema_version": "1.1",
        "ready": ready,
        "project": "polar-baseline",
        "source": {
            "mode": "AGENTTEAMS_RUN" if is_agentteams else "LOCAL_DEMO",
            "label": "AgentTeams 真实协作记录" if is_agentteams else "本地内置演示",
            "read_only": True,
        },
        "principles": ["无证据不诊断", "无审批不执行", "无验证不闭环"],
        "summary": {
            "allowed_files": allowed_files,
            "snapshot_status": summary.get("verification_status", registry.get("verification_status", "NOT_RUN")),
            "evidence_count": evidence_count,
            "gaps_count": gaps_count,
            "demo_verification": demo_verification,
            "incident_state": incident_state,
            "underlying_issue_resolved": underlying_issue_resolved,
            "trace_chain_ok": bool(summary.get("trace_chain_ok", trace_ok)) and trace_ok,
        },
        "stages": [
            {"id": "snapshot", "label": "快照登记", "value": registry.get("verification_status", "NOT_RUN"), "ok": registry.get("verification_status") == "VERIFIED"},
            {"id": "evidence", "label": "证据采集", "value": f"{len(evidence)} 项证据", "ok": bool(evidence)},
            {"id": "diagnosis", "label": "受控诊断", "value": f"{len(hypotheses)} 个假设", "ok": bool(hypotheses)},
            {"id": "approval", "label": "人工审批", "value": f"{len(approvals)} 个请求", "ok": bool(approvals)},
            {"id": "action", "label": "受控动作", "value": f"{len(action_events)} 条记录", "ok": bool(action_events)},
            {"id": "verify", "label": "验证闭环", "value": incident_state, "ok": demo_verification == "PASSED"},
        ],
        "evidence": evidence,
        "gaps": gaps,
        "hypotheses": hypotheses,
        "hypothesis_counts": _counts(hypotheses, "state"),
        "approvals": approvals,
        "approval_counts": approval_counts,
        "verification": verification,
        "agentteams": {
            "enabled": is_agentteams,
            "task_id": manifest.get("task_id"),
            "incident_id": manifest.get("incident_id", verification.get("incident_id")),
            "agents": agents,
            "handoff_count": int(manifest.get("handoff_count", 0)) if is_agentteams else 0,
            "handoffs": handoffs,
            "package_time": manifest.get("package_time"),
            "execution": {
                "owner": execution.get("owner"),
                "mode": execution.get("mode"),
                "status": execution_result.get("status"),
                "simulated": bool(execution_result.get("simulated", False)),
                "approval_id": execution.get("approval", {}).get("approval_id") if isinstance(execution.get("approval"), dict) else None,
                "decided_by": execution.get("approval", {}).get("decided_by") if isinstance(execution.get("approval"), dict) else None,
            },
            "unresolved_limitations": manifest.get("unresolved_limitations", []) if is_agentteams else [],
        },
        "trace": {
            "ok": trace_ok,
            "message": trace_message,
            "entries": len(trace_records),
            "recent": trace_records[-12:][::-1],
        },
        "safety": {
            "excluded_data_not_read": bool(summary.get("excluded_data_not_read", registry.get("excluded_data_not_read", False))),
            "no_fabricated_faults": bool(summary.get("no_fabricated_faults", False)),
            "no_polar_root_cause_claim": bool(summary.get("no_polar_root_cause_claim", False)),
            "no_model_optimization": bool(summary.get("no_model_optimization", False)),
            "network_required": False,
            "risky_actions_simulated": True,
            "prohibited_operations_zero": bool(is_agentteams and all(
                value == 0 for value in manifest.get("prohibited_operations_zero", {}).values()
            )),
        },
    }


def run_bundled_demo(workspace: str | Path, project_root: str | Path) -> int:
    """Generate demo output once when a workspace has no existing summary."""
    from labops.demo import run_demo

    workspace = Path(workspace)
    project_root = Path(project_root)
    summary = workspace / "demo" / "demo_summary.json"
    if summary.exists():
        return 0
    fixtures = project_root / "demo" / "fixtures"
    return run_demo(
        workspace=workspace,
        snapshot_dir=fixtures / "project_snapshot_lite",
        audit_dir=fixtures / "audit",
        verification_json=fixtures / "snapshot_verification.json",
        allowed_list=project_root / "demo" / "allowed_files.json",
        trace=TraceLog(workspace / "trace.jsonl"),
    )


def make_handler(workspace: str | Path):
    workspace = Path(workspace).resolve()
    dashboard_html = Path(__file__).with_name("dashboard.html")

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "LabOpsGuard/1.0"

        def _headers(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
            self.end_headers()

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self._headers(status, content_type, len(body))
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            path = self.path.split("?", 1)[0]
            if path == "/":
                try:
                    body = dashboard_html.read_bytes()
                except OSError as exc:
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                self._send(200, "text/html; charset=utf-8", body)
            elif path == "/api/status":
                self._json(200, build_dashboard_state(workspace))
            elif path == "/healthz":
                state = build_dashboard_state(workspace)
                self._json(200 if state["ready"] else 503, {"ok": state["ready"], "service": "labops-guard"})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            # Drain the request body before rejecting it. On Windows, closing a
            # socket with unread request bytes can reset the connection before
            # urllib receives the intended HTTP 405 response.
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 0:
                self.rfile.read(content_length)
            self._json(405, {"ok": False, "error": "dashboard is read-only"})

        def log_message(self, fmt: str, *args) -> None:
            print(f"[dashboard] {self.client_address[0]} {fmt % args}")

    return DashboardHandler


def serve(workspace: str | Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Serve the dashboard until interrupted."""
    server = ThreadingHTTPServer((host, port), make_handler(workspace))
    print(f"LabOps Guard dashboard: http://{host}:{port}")
    print(f"Workspace: {Path(workspace).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
