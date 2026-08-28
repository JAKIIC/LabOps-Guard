from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from labops.live_demo import prepare_session
from labops.matrix_observer import write_observer_projection
from labops.web import make_handler, run_bundled_demo


ROOT = Path(__file__).resolve().parent.parent


class ReviewerWebTests(unittest.TestCase):
    SESSION_ID = "20260831-091"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "dashboard-output"
        self.sessions = self.root / "live-sessions"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_bundled_demo(self.workspace, ROOT), 0)
        prepared = prepare_session(ROOT, self.sessions, self.SESSION_ID)
        self.session_root = Path(prepared["session_root"])
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        events = [
            self._event("$rca-planner", "rca_to_planner", "rca-analyst", "DIAGNOSIS_READY", "PLANNING", now),
            self._event("$policy", "policy_passed", "experiment-planner", "PLAN_READY", "POLICY_CHECKING", now),
            self._event("$approval", "approval_pending", "experiment-planner", "POLICY_CHECKING", "APPROVAL_PENDING", now),
        ]
        write_observer_projection(self.session_root, {
            "connected": True,
            "source_status": "LIVE",
            "checked_at": now,
            "last_success_at": now,
            "next_batch": "s-reviewer-1",
            "events": events,
            "errors": [],
        })
        self.context = {
            "project_root": ROOT,
            "sessions_root": self.sessions,
            "mode": "live",
            "preflight": {"status": "READY", "requirements": {"matrix": True}},
        }
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.workspace, reviewer_context=self.context),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    @staticmethod
    def _event(
        event_id: str,
        kind: str,
        actor: str,
        workflow_from: str,
        workflow_to: str,
        timestamp: str,
    ) -> dict:
        return {
            "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
            "event_id": event_id,
            "room_id": "!private-reviewer-room:matrix.example.invalid",
            "actor": actor,
            "kind": kind,
            "timestamp": timestamp,
            "workflow_from": workflow_from,
            "workflow_to": workflow_to,
            "evidence_state": "OBSERVED",
            "artifact_refs": [f"shared/{kind}.json"],
            "hash_refs": ["a" * 64],
        }

    def _json(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            self.assertEqual(response.headers.get_content_type(), "application/json")
            return json.load(response)

    def test_existing_dashboard_routes_remain_compatible(self) -> None:
        html = urllib.request.urlopen(self.base + "/", timeout=3).read().decode("utf-8")
        self.assertIn("LabOps Guard", html)
        self.assertTrue(self._json("/api/status")["ready"])
        self.assertTrue(self._json("/healthz")["ok"])

    def test_preflight_and_status_are_read_only_and_truthful(self) -> None:
        preflight = self._json("/api/reviewer/preflight")
        self.assertTrue(preflight["read_only"])
        self.assertEqual(preflight["mode"], "LIVE")
        self.assertEqual(preflight["status"], "READY")

        status = self._json(f"/api/reviewer/status?session={self.SESSION_ID}")
        self.assertTrue(status["read_only"])
        self.assertEqual(status["mode"], "LIVE")
        self.assertEqual(status["source_summary"], "LIVE_PARTIAL")
        self.assertEqual(status["incident"]["current_owner"], "Human Approver")
        event = next(item for item in status["timeline"] if item["kind"] == "rca_to_planner")
        self.assertNotIn("event_id", event)
        self.assertNotIn("hash_refs", event)
        self.assertEqual(event["details"]["event_id"], "$rca-planner")
        self.assertEqual(event["details"]["hash_refs"], ["a" * 64])

    def test_events_are_incremental_bounded_and_use_details(self) -> None:
        first = self._json(f"/api/reviewer/events?session={self.SESSION_ID}&after=0")
        self.assertTrue(first["read_only"])
        self.assertEqual(len(first["events"]), 3)
        self.assertEqual(first["next_after"], 3)
        self.assertEqual(first["events"][0]["sequence"], 1)
        self.assertNotIn("event_id", first["events"][0])
        self.assertEqual(first["events"][0]["details"]["event_id"], "$rca-planner")
        second = self._json(f"/api/reviewer/events?session={self.SESSION_ID}&after=1")
        self.assertEqual([item["sequence"] for item in second["events"]], [2, 3])

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._json(f"/api/reviewer/events?session={self.SESSION_ID}&after=-1")
        self.assertEqual(caught.exception.code, 400)

    def test_invalid_and_missing_sessions_fail_closed_without_path_disclosure(self) -> None:
        traversal = urllib.parse.quote("../output-agentteams-at004", safe="")
        for path, expected in (
            (f"/api/reviewer/status?session={traversal}", 400),
            ("/api/reviewer/status?session=20260831-999", 404),
        ):
            with self.subTest(path=path):
                request = urllib.request.Request(self.base + path)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=3)
                self.assertEqual(caught.exception.code, expected)
                body = caught.exception.read().decode("utf-8")
                self.assertNotIn("output-agentteams-at004", body)
                self.assertNotIn(str(self.sessions), body)

    def test_reviewer_endpoints_reject_every_write_method(self) -> None:
        paths = [
            "/api/reviewer/preflight",
            f"/api/reviewer/status?session={self.SESSION_ID}",
            f"/api/reviewer/events?session={self.SESSION_ID}&after=0",
        ]
        for path in paths:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(path=path, method=method):
                    request = urllib.request.Request(self.base + path, data=b"{}", method=method)
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(caught.exception.code, 405)

    def test_excluded_files_tokens_paths_and_private_room_ids_are_not_served(self) -> None:
        token = "LOCAL-MATRIX-TOKEN-MUST-NOT-LEAK"
        host_path = "C:/Users/private/operator/secrets.json"
        room_id = "!private-reviewer-room:matrix.example.invalid"
        (self.session_root / "local-secrets.json").write_text(
            json.dumps({"token": token, "path": host_path, "room": room_id}), encoding="utf-8",
        )
        (self.session_root / "observer" / "ignored-debug.log").write_text(
            f"{token} {host_path}", encoding="utf-8",
        )
        payloads = [
            self._json(f"/api/reviewer/status?session={self.SESSION_ID}"),
            self._json(f"/api/reviewer/events?session={self.SESSION_ID}&after=0"),
        ]
        rendered = json.dumps(payloads, ensure_ascii=False)
        self.assertNotIn(token, rendered)
        self.assertNotIn(host_path, rendered)
        self.assertNotIn(room_id, rendered)

    def test_malformed_observer_cache_is_blocked_not_replayed(self) -> None:
        (self.session_root / "observer" / "source_status.json").write_text("{broken", encoding="utf-8")
        request = urllib.request.Request(
            self.base + f"/api/reviewer/status?session={self.SESSION_ID}"
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 503)
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["archived_replay_used"])
        self.assertNotIn(str(self.session_root), json.dumps(payload))

    def test_tampered_event_reference_is_blocked_without_disclosure(self) -> None:
        event_path = self.session_root / "observer" / "normalized_events.jsonl"
        event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
        private_path = "C:/Users/private/operator/token.txt"
        event["artifact_refs"] = [private_path]
        event_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        request = urllib.request.Request(
            self.base + f"/api/reviewer/status?session={self.SESSION_ID}"
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 503)
        payload = caught.exception.read().decode("utf-8")
        self.assertNotIn(private_path, payload)
        self.assertIn("REVIEWER_SOURCE_INVALID", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
