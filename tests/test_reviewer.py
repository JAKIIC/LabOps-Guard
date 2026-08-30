from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import subprocess
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from labops import cli, reviewer as reviewer_mod
from labops.reviewer import (
    build_preflight,
    reviewer_status,
    start_reviewer,
    stop_reviewer,
)


ROOT = Path(__file__).resolve().parent.parent
FORMAL_BUNDLES = (
    ROOT / "demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip",
    ROOT / "demo/output-agentteams-at003/artifacts/DEMO-RCA-003/LABOPS-AT-003-evidence-bundle.zip",
    ROOT / "demo/output-agentteams-at004/LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip",
)
REAL_ROOM_MAP = {
    "schema_version": "1.0",
    "rooms": {
        "!manager:matrix-local.hiclaw.io": "labops-manager",
        "!collector:matrix-local.hiclaw.io": "evidence-collector",
        "!rca:matrix-local.hiclaw.io": "rca-analyst",
        "!planner:matrix-local.hiclaw.io": "experiment-planner",
        "!executor:matrix-local.hiclaw.io": "safe-executor",
        "!auditor:matrix-local.hiclaw.io": "verification-auditor",
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ready(mode: str) -> dict:
    return {
        "schema_version": "1.0",
        "requested_mode": mode.upper(),
        "status": "READY",
        "available_modes": ["QUICK", "LIVE"] if mode == "live" else ["QUICK"],
        "checks": {},
        "missing_requirements": [],
        "fallback": {"mode": "QUICK"},
        "safety": ["read-only workbench"],
    }


class ReviewerBusinessReadinessProbeTests(unittest.TestCase):
    def test_probe_uses_live_channel_status_instead_of_gateway_health_projection(self) -> None:
        channel_status = {
            "channels": {"matrix": {"configured": True, "running": True}},
            "channelAccounts": {
                "matrix": [
                    {
                        "accountId": "default",
                        "configured": True,
                        "running": True,
                        "connected": True,
                        "healthState": "healthy",
                    }
                ]
            },
        }
        gateway_health = {
            "ok": True,
            "channels": {
                "matrix": {
                    "configured": True,
                    "running": False,
                    "probe": {"ok": True},
                }
            },
        }

        def fake_run(command, **_kwargs):
            payload = channel_status if "channels" in command and "status" in command else gateway_health
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

        with (
            patch("labops.reviewer.shutil.which", return_value="docker"),
            patch("labops.reviewer.subprocess.run", side_effect=fake_run),
        ):
            result = reviewer_mod._probe_agentteams_business_readiness(ROOT)

        self.assertTrue(result["ready"])
        self.assertEqual(result["ready_count"], 6)
        self.assertEqual(set(result["components"].values()), {"READY"})


class _FakeComponent:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.started = 0
        self.stopped = 0
        self.alive = False

    def start(self) -> None:
        self.started += 1
        self.alive = True
        self.events.append(f"start:{self.name}")

    def stop(self) -> None:
        self.stopped += 1
        self.alive = False
        self.events.append(f"stop:{self.name}")

    def is_alive(self) -> bool:
        return self.alive


class ReviewerPreflightTests(unittest.TestCase):
    def test_quick_mode_verifies_repository_and_formal_evidence_without_matrix(self) -> None:
        report = build_preflight(ROOT, "quick", environment={})

        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["requested_mode"], "QUICK")
        self.assertIn("QUICK", report["available_modes"])
        self.assertEqual(report["missing_requirements"], [])
        self.assertEqual(report["checks"]["trust_contract"]["status"], "PASS")
        self.assertEqual(report["checks"]["formal_evidence"]["status"], "PASS")
        self.assertEqual(len(report["checks"]["formal_evidence"]["bundles"]), 3)
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn("MATRIX_ACCESS_TOKEN", rendered)

    def test_live_mode_lists_every_missing_external_prerequisite(self) -> None:
        report = build_preflight(
            ROOT,
            "live",
            environment={},
            docker_probe=lambda _root: {"docker": False, "runner_image": False},
        )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(
            report["missing_requirements"],
            [
                "DOCKER_UNAVAILABLE",
                "RUNNER_IMAGE_MISSING",
                "MATRIX_HOMESERVER_MISSING",
                "MATRIX_ACCESS_TOKEN_MISSING",
                "MATRIX_ROOM_MAP_MISSING",
            ],
        )
        self.assertEqual(report["fallback"]["mode"], "QUICK")

    def test_live_mode_accepts_a_valid_room_allowlist_without_exposing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room_map = Path(tmp) / "rooms.json"
            room_map.write_text(json.dumps(REAL_ROOM_MAP), encoding="utf-8")
            environment = {
                "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                "LABOPS_MATRIX_ACCESS_TOKEN": "reviewer-secret-token",
                "LABOPS_MATRIX_ROOM_MAP": str(room_map),
            }
            report = build_preflight(
                ROOT,
                "live",
                environment=environment,
                docker_probe=lambda _root: {"docker": True, "runner_image": True},
                agentteams_probe=lambda _root: {
                    "ready": True,
                    "ready_count": 6,
                    "required": 6,
                    "components": {},
                },
                matrix_probe=lambda _homeserver, _token, roles: {
                    "connected": True,
                    "all_joined": True,
                    "rooms_expected": len(roles),
                    "error": None,
                },
            )

        self.assertEqual(report["status"], "READY")
        self.assertIn("LIVE", report["available_modes"])
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("reviewer-secret-token", rendered)
        self.assertNotIn(str(room_map), rendered)

    def test_live_mode_blocks_a_well_formed_but_unjoined_room_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room_map = Path(tmp) / "rooms.json"
            room_map.write_text(json.dumps(REAL_ROOM_MAP), encoding="utf-8")
            report = build_preflight(
                ROOT,
                "live",
                environment={
                    "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                    "LABOPS_MATRIX_ACCESS_TOKEN": "reviewer-secret-token",
                    "LABOPS_MATRIX_ROOM_MAP": str(room_map),
                },
                docker_probe=lambda _root: {"docker": True, "runner_image": True},
                agentteams_probe=lambda _root: {
                    "ready": True,
                    "ready_count": 6,
                    "required": 6,
                    "components": {},
                },
                matrix_probe=lambda _homeserver, _token, roles: {
                    "connected": True,
                    "all_joined": False,
                    "rooms_expected": len(roles),
                    "error": "MATRIX_ROOM_MAP_UNJOINED",
                },
            )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("MATRIX_ROOM_MAP_UNJOINED", report["missing_requirements"])
        self.assertEqual(report["checks"]["matrix_room_membership"]["status"], "FAIL")

    def test_live_mode_blocks_when_a_running_worker_is_not_consuming_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room_map = Path(tmp) / "rooms.json"
            room_map.write_text(json.dumps(REAL_ROOM_MAP), encoding="utf-8")
            report = build_preflight(
                ROOT,
                "live",
                environment={
                    "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                    "LABOPS_MATRIX_ACCESS_TOKEN": "reviewer-secret-token",
                    "LABOPS_MATRIX_ROOM_MAP": str(room_map),
                },
                docker_probe=lambda _root: {"docker": True, "runner_image": True},
                agentteams_probe=lambda _root: {
                    "ready": False,
                    "ready_count": 5,
                    "required": 6,
                    "components": {
                        "labops-manager": "READY",
                        "evidence-collector": "MATRIX_STOPPED",
                    },
                },
                matrix_probe=lambda _homeserver, _token, roles: {
                    "connected": True,
                    "all_joined": True,
                    "rooms_expected": len(roles),
                    "error": None,
                },
            )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("AGENTTEAMS_BUSINESS_NOT_READY", report["missing_requirements"])
        self.assertEqual(report["checks"]["agentteams_business_readiness"]["status"], "FAIL")
        self.assertEqual(report["checks"]["agentteams_business_readiness"]["ready"], 5)


class ReviewerLifecycleTests(unittest.TestCase):
    def _factory(self, events: list[str], components: dict[str, _FakeComponent]):
        def factory(kind: str, **_kwargs) -> _FakeComponent:
            self.assertNotIn(kind, components)
            component = _FakeComponent(kind, events)
            components[kind] = component
            return component
        return factory

    def test_quick_start_stays_foreground_and_stops_server_on_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events: list[str] = []
            components: dict[str, _FakeComponent] = {}
            started: list[dict] = []
            waits = 0

            def wait(_seconds: float) -> None:
                nonlocal waits
                waits += 1
                raise KeyboardInterrupt

            result = start_reviewer(
                ROOT,
                Path(tmp),
                "quick",
                component_factory=self._factory(events, components),
                preflight_builder=lambda *_args, **_kwargs: _ready("quick"),
                wait_fn=wait,
                open_browser=False,
                on_started=started.append,
            )

            lifecycle = json.loads(
                (Path(tmp) / ".reviewer/lifecycle.json").read_text(encoding="utf-8")
            )

        self.assertEqual(waits, 1)
        self.assertEqual(list(components), ["web"])
        self.assertEqual(components["web"].started, 1)
        self.assertEqual(components["web"].stopped, 1)
        self.assertEqual(events, ["start:web", "stop:web"])
        self.assertEqual(started[0]["status"], "RUNNING")
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(lifecycle["status"], "STOPPED")

    def test_start_rejects_an_unresolved_ephemeral_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = start_reviewer(
                ROOT,
                Path(tmp),
                "quick",
                port=0,
                component_factory=lambda *_args, **_kwargs: self.fail("component must not start"),
                preflight_builder=lambda *_args, **_kwargs: _ready("quick"),
                open_browser=False,
            )

        self.assertEqual(result, {"status": "BLOCKED", "error": "INVALID_REVIEWER_PORT"})

    def test_container_bind_uses_bridge_wildcard_but_keeps_public_url_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events: list[str] = []
            observed_options: list[dict] = []
            started: list[dict] = []

            def factory(kind: str, **options):
                observed_options.append(options)
                return _FakeComponent(kind, events)

            def wait(_seconds: float) -> None:
                raise KeyboardInterrupt

            result = start_reviewer(
                ROOT,
                Path(tmp),
                "quick",
                container_bind=True,
                component_factory=factory,
                preflight_builder=lambda *_args, **_kwargs: _ready("quick"),
                wait_fn=wait,
                open_browser=False,
                on_started=started.append,
            )
            lifecycle = json.loads(
                (Path(tmp) / ".reviewer/lifecycle.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(observed_options[0]["host"], "0.0.0.0")
        self.assertEqual(started[0]["url"], "http://127.0.0.1:18787/reviewer")
        self.assertEqual(lifecycle["host"], "127.0.0.1")
        self.assertEqual(lifecycle["bind_scope"], "CONTAINER_BRIDGE")

    def test_quick_start_refuses_to_write_lifecycle_inside_formal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            formal = project / "demo/output-agentteams-at004"
            formal.mkdir(parents=True)
            result = start_reviewer(
                project,
                formal,
                "quick",
                component_factory=lambda *_args, **_kwargs: self.fail("component must not start"),
                preflight_builder=lambda *_args, **_kwargs: _ready("quick"),
                open_browser=False,
            )

            lifecycle_written = (formal / ".reviewer").exists()

        self.assertEqual(result, {"status": "BLOCKED", "error": "FORMAL_EVIDENCE_ROOT_FORBIDDEN"})
        self.assertFalse(lifecycle_written)

    def test_live_start_rejects_gateway_binding_outside_local_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            result = start_reviewer(
                ROOT,
                sessions,
                "live",
                session_id="20260831-097",
                gateway_host="203.0.113.10",
                component_factory=lambda *_args, **_kwargs: self.fail("component must not start"),
                preflight_builder=lambda *_args, **_kwargs: _ready("live"),
                open_browser=False,
            )

            session_created = (sessions / "20260831-097").exists()

        self.assertEqual(result, {"status": "BLOCKED", "error": "GATEWAY_HOST_OUTSIDE_LOCAL_BOUNDARY"})
        self.assertFalse(session_created)

    def test_later_component_failure_cleans_only_components_already_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events: list[str] = []
            gateway = _FakeComponent("gateway", events)

            def factory(kind: str, **_kwargs):
                if kind == "gateway":
                    return gateway
                raise RuntimeError("observer construction failed")

            result = start_reviewer(
                ROOT,
                Path(tmp),
                "live",
                session_id="20260831-096",
                component_factory=factory,
                preflight_builder=lambda *_args, **_kwargs: _ready("live"),
                open_browser=False,
            )

        self.assertEqual(events, ["start:gateway", "stop:gateway"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error"], "RuntimeError")

    def test_live_start_creates_isolated_session_and_owns_all_components(self) -> None:
        before = [_sha(path) for path in FORMAL_BUNDLES]
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            events: list[str] = []
            components: dict[str, _FakeComponent] = {}
            waits = 0

            def wait(_seconds: float) -> None:
                nonlocal waits
                waits += 1
                raise KeyboardInterrupt

            result = start_reviewer(
                ROOT,
                sessions,
                "live",
                session_id="20260831-095",
                environment={
                    "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                    "LABOPS_MATRIX_ACCESS_TOKEN": "not-serialized",
                    "LABOPS_MATRIX_ROOM_MAP": "ignored-by-fake-factory.json",
                },
                component_factory=self._factory(events, components),
                preflight_builder=lambda *_args, **_kwargs: _ready("live"),
                wait_fn=wait,
                open_browser=False,
            )
            session_root = sessions / "20260831-095"
            manifest = json.loads((session_root / "session.json").read_text(encoding="utf-8"))
            evidence_files = list((session_root / "evidence").iterdir())

        self.assertEqual(waits, 1)
        self.assertEqual(list(components), ["gateway", "observer", "web"])
        self.assertEqual(events[:3], ["start:gateway", "start:observer", "start:web"])
        self.assertEqual(events[3:], ["stop:web", "stop:observer", "stop:gateway"])
        self.assertTrue(all(item.started == 1 and item.stopped == 1 for item in components.values()))
        self.assertEqual(manifest["classification"], "NON_FORMAL_LIVE_DEMO")
        self.assertEqual(evidence_files, [])
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(before, [_sha(path) for path in FORMAL_BUNDLES])

    def test_status_and_stop_use_only_a_fresh_recorded_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            runtime = sessions / ".reviewer"
            runtime.mkdir(parents=True)
            record = {
                "schema_version": "1.0",
                "classification": "LOCAL_REVIEWER_LIFECYCLE",
                "instance_id": "instance-123",
                "pid": 43210,
                "mode": "QUICK",
                "session_id": None,
                "host": "127.0.0.1",
                "port": 18787,
                "gateway_port": None,
                "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "heartbeat_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "status": "RUNNING",
                "url": "http://127.0.0.1:18787/reviewer",
                "read_only": True,
            }
            (runtime / "lifecycle.json").write_text(json.dumps(record), encoding="utf-8")

            status = reviewer_status(
                sessions,
                process_probe=lambda pid: pid == 43210,
                health_probe=lambda url: url == "http://127.0.0.1:18787/api/reviewer/preflight",
            )
            stopped = stop_reviewer(sessions, process_probe=lambda pid: pid == 43210)
            request = json.loads(
                (runtime / "stop-instance-123.json").read_text(encoding="utf-8")
            )

        self.assertEqual(status["status"], "RUNNING")
        self.assertEqual(stopped["status"], "STOP_REQUESTED")
        self.assertEqual(request["pid"], 43210)
        self.assertEqual(request["instance_id"], "instance-123")

    def test_stop_is_clean_when_missing_and_blocks_unresolved_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self.assertEqual(stop_reviewer(sessions)["status"], "NOT_RUNNING")
            runtime = sessions / ".reviewer"
            runtime.mkdir(parents=True)
            (runtime / "lifecycle.json").write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "classification": "LOCAL_REVIEWER_LIFECYCLE",
                    "instance_id": "bad-instance",
                    "pid": 0,
                    "status": "RUNNING",
                }),
                encoding="utf-8",
            )
            result = stop_reviewer(sessions, process_probe=lambda _pid: True)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error"], "INVALID_LIFECYCLE_RECORD")

    def test_windows_process_probe_is_read_only_and_never_calls_os_kill(self) -> None:
        tasklist = subprocess.CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"python.exe","43210","Console","1","10,000 K"\n',
            stderr="",
        )
        with (
            patch.object(reviewer_mod.os, "name", "nt"),
            patch.object(reviewer_mod.subprocess, "run", return_value=tasklist),
            patch.object(reviewer_mod.os, "kill", side_effect=AssertionError("must not signal")),
        ):
            alive = reviewer_mod._pid_alive(43210)

        self.assertTrue(alive)


class ReviewerCLITests(unittest.TestCase):
    def test_cli_registers_preflight_status_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with patch("labops.reviewer.build_preflight", return_value=_ready("quick")):
                with redirect_stdout(output):
                    rc = cli.main(["reviewer", "preflight", "--mode", "quick"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())["requested_mode"], "QUICK")

            output = io.StringIO()
            with redirect_stdout(output):
                rc = cli.main(["reviewer", "stop", "--sessions-root", tmp])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "NOT_RUNNING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
