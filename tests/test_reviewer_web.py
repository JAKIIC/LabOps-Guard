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
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from labops.live_demo import prepare_session
from labops.matrix_observer import write_observer_projection
from labops.web import make_handler, run_bundled_demo


ROOT = Path(__file__).resolve().parent.parent


class _VisibleHTMLParser(HTMLParser):
    """Collect visible text and interactive elements from the served page."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden_depth = 0
        self.text: list[str] = []
        self.interactive_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if tag in {"button", "form", "input", "select", "textarea"}:
            self.interactive_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and data.strip():
            self.text.append(data.strip())


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
            "validation_version": "matrix-sender-bound-v1",
            "event_id": event_id,
            "room_id": "!private-reviewer-room:matrix.example.invalid",
            "session_id": ReviewerWebTests.SESSION_ID,
            "task_instance_id": f"LIVE-TASK-{ReviewerWebTests.SESSION_ID}",
            "incident_instance_id": f"LIVE-INCIDENT-{ReviewerWebTests.SESSION_ID}",
            "attempt_id": f"LIVE-ATTEMPT-{ReviewerWebTests.SESSION_ID}-01",
            "run_id": f"RUN-LABOPS-AT-004-AGENTTEAMS-{ReviewerWebTests.SESSION_ID[-3:]}",
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

    def _html(self, path: str) -> tuple[str, str]:
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            self.assertEqual(response.headers.get_content_type(), "text/html")
            html = response.read().decode("utf-8")
        parser = _VisibleHTMLParser()
        parser.feed(html)
        return html, " ".join(parser.text)

    def test_existing_dashboard_routes_remain_compatible(self) -> None:
        html = urllib.request.urlopen(self.base + "/", timeout=3).read().decode("utf-8")
        self.assertIn("LabOps Guard", html)
        self.assertTrue(self._json("/api/status")["ready"])
        self.assertTrue(self._json("/healthz")["ok"])

    def test_reviewer_page_serves_frozen_read_only_semantics(self) -> None:
        html, visible_text = self._html("/reviewer")
        self.assertEqual(html, (ROOT / "labops" / "reviewer.html").read_text(encoding="utf-8"))
        for marker in (
            "人工审批门",
            "当前指令",
            "已配置策略",
            "工作流状态",
            "证据状态",
            "最后活动 Agent",
            "最后事件 / 更新时间",
            "Tool Contract",
            "Protected Resources",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, visible_text)
        parser = _VisibleHTMLParser()
        parser.feed(html)
        self.assertEqual(parser.interactive_tags, [])
        self.assertNotIn("LIVE MODE", visible_text)
        self.assertIn("完全只读", visible_text)

    def test_reviewer_page_uses_chinese_primary_labels_with_technical_terms_preserved(self) -> None:
        html, visible_text = self._html("/reviewer")
        for marker in (
            "LabOps Guard · Reviewer Edition",
            "面向生产级 Agent 系统的可信执行与治理基础设施",
            "当前事故",
            "当前责任人",
            "最后活动 Agent",
            "最后事件 / 更新时间",
            "AgentTeams 协作时间线",
            "人工审批门",
            "Tool Contract",
            "恢复 / 升级处理",
            "Runner",
            "Auditor",
            "完全只读",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, visible_text)

        for redundant_label in (
            "可信 Agent 执行审查台",
            "Current Incident",
            "Current Owner",
            "Last Active Agent",
            "Last Event / Last Updated",
            "Workflow State",
            "Evidence State",
            "Current Directive",
            "Configured Policy",
            "Human Approval Gate",
            "Read-only",
        ):
            with self.subTest(redundant_label=redundant_label):
                self.assertNotIn(redundant_label, visible_text)

        # Identifiers and runtime status codes remain available for evidence review.
        for technical_marker in (
            "Reviewer Edition",
            "Incident ID",
            "Task ID",
            "Run ID",
            "VERIFIED",
            "RESOLVED",
            "DISCONNECTED",
        ):
            with self.subTest(technical_marker=technical_marker):
                self.assertIn(technical_marker, html)

        for runtime_explanation in (
            "任务已派发",
            "证据收集完成",
            "证据不完整",
            "补齐证据缺口并创建新 attempt",
            "REPLAY 为不可变的历史归档运行",
        ):
            with self.subTest(runtime_explanation=runtime_explanation):
                self.assertIn(runtime_explanation, html)

    def test_reviewer_page_polls_only_read_only_reviewer_apis(self) -> None:
        html, _ = self._html("/reviewer")
        self.assertIn('fetch(`/api/reviewer/status', html)
        self.assertIn('fetch(`/api/reviewer/events', html)
        self.assertIn("setInterval(poll, 1000)", html)
        self.assertNotIn("method:", html)
        self.assertNotIn("/api/status", html)

    def test_reviewer_page_keeps_green_for_verified_and_resolved_only(self) -> None:
        html, _ = self._html("/reviewer")
        self.assertIn(".is-verified", html)
        self.assertIn(".is-resolved", html)
        for selector in (
            ".is-active",
            ".is-observed",
            ".is-waiting",
            ".is-configured",
            ".is-unverified",
            ".is-not-started",
            ".is-blocked",
            ".is-rejected",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, html)
        self.assertIn("ACTIVE: 'is-active'", html)
        self.assertIn("OBSERVED: 'is-observed'", html)
        self.assertIn("WAITING: 'is-waiting'", html)
        self.assertIn("UNVERIFIED: 'is-unverified'", html)
        self.assertIn("NOT_STARTED: 'is-not-started'", html)
        self.assertNotIn("ACTIVE: 'is-verified'", html)
        self.assertNotIn("OBSERVED: 'is-verified'", html)
        self.assertNotIn("WAITING: 'is-verified'", html)
        self.assertNotIn("UNVERIFIED: 'is-verified'", html)
        self.assertNotIn("NOT_STARTED: 'is-verified'", html)

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
            "/reviewer",
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

    def test_legacy_event_without_sender_validation_version_is_blocked(self) -> None:
        event_path = self.session_root / "observer" / "normalized_events.jsonl"
        event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
        event.pop("validation_version")
        event_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

        request = urllib.request.Request(
            self.base + f"/api/reviewer/status?session={self.SESSION_ID}"
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)

        self.assertEqual(caught.exception.code, 503)
        self.assertIn("REVIEWER_SOURCE_INVALID", caught.exception.read().decode("utf-8"))

    def test_evidence_incomplete_is_a_valid_dynamic_projection_event(self) -> None:
        event_path = self.session_root / "observer" / "normalized_events.jsonl"
        gap = self._event(
            "$evidence-gap",
            "evidence_incomplete",
            "evidence-collector",
            "EVIDENCE_COLLECTING",
            "BLOCKED",
            "2026-08-28T11:59:56Z",
        )
        event_path.write_text(json.dumps(gap) + "\n", encoding="utf-8")

        payload = self._json(
            f"/api/reviewer/events?session={self.SESSION_ID}&after=0"
        )

        self.assertEqual(payload["events"][0]["kind"], "evidence_incomplete")
        self.assertEqual(payload["events"][0]["actor"], "evidence-collector")


if __name__ == "__main__":
    unittest.main(verbosity=2)
