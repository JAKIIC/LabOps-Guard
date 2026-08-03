"""Short-lived, allowlisted control plane for AgentTeams Safe Executor.

The gateway is not an experiment runtime and is not an Agent. It accepts only
one LABOPS-AT-003 plan shape and starts the network-disabled Runner through the
host Docker adapter. It should be stopped after the AgentTeams run.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from labops.runner import RUNNER_IMAGE, execute_runner_plan


MAX_BODY = 64 * 1024
RUN_ID = re.compile(r"^RUN-LABOPS-AT-003-AGENTTEAMS-[0-9]{3}$")


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
    demo = repo_root / "demos" / "checkpoint-regression"
    baseline = repo_root / "artifacts" / "DEMO-RCA-001" / "baseline" / "run-01"

    class Handler(BaseHTTPRequestHandler):
        server_version = "LabOpsRunnerGateway/0.1.0"

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"ok": True, "service": "labops-runner-gateway", "runner_image": RUNNER_IMAGE})
            else:
                self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/run":
                self._send(404, {"ok": False, "error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self._send(413, {"ok": False, "error": "invalid request size"})
                return
            try:
                request = json.loads(self.rfile.read(length))
                plan = request["experiment_plan"]
                approval = request["approval"]
            except (KeyError, json.JSONDecodeError, TypeError):
                self._send(400, {"ok": False, "error": "structured experiment_plan and approval required"})
                return
            run_id = str(plan.get("run_id", ""))
            allowed = (
                plan.get("task_id") == "LABOPS-AT-003"
                and plan.get("incident_id") == "DEMO-RCA-003"
                and RUN_ID.fullmatch(run_id) is not None
                and plan.get("runtime", {}).get("image") == RUNNER_IMAGE
                and approval.get("task_id") == "LABOPS-AT-003"
                and approval.get("decision") == "APPROVED"
                and bool(approval.get("approval_id"))
                and bool(approval.get("decided_by"))
                and bool(approval.get("approved_at"))
            )
            if not allowed:
                self._send(403, {"ok": False, "error": "task, runner, run_id or human approval is outside the fixed contract"})
                return
            if not lock.acquire(blocking=False):
                self._send(409, {"ok": False, "error": "runner busy"})
                return
            try:
                run_dir = output_root / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "gateway_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                result = execute_runner_plan(plan, demo, baseline, run_dir)
                response = {
                    "ok": result.get("status") == "completed",
                    "task_id": "LABOPS-AT-003",
                    "run_id": run_id,
                    "approval_id": approval["approval_id"],
                    "control_plane": "short-lived local gateway",
                    "experiment_network": "none",
                    "runner_image": RUNNER_IMAGE,
                    "artifacts": _read_outputs(run_dir),
                }
                (run_dir / "gateway_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
                self._send(200 if response["ok"] else 422, response)
            except Exception as exc:
                self._send(500, {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:500]})
            finally:
                lock.release()

        def log_message(self, fmt: str, *args) -> None:
            print(f"[runner-gateway] {self.client_address[0]} {fmt % args}", flush=True)

    return Handler


def serve(repo_root: str | Path, output_root: str | Path, host: str = "0.0.0.0", port: int = 18103) -> None:
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
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18103)
    args = parser.parse_args()
    serve(args.repo_root, args.output_root, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
