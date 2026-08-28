from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from labops.contracts import validate_document
from labops.live_demo import prepare_session
from labops.matrix_observer import (
    load_room_map,
    normalize_sync_response,
    sync_once,
    write_observer_projection,
)


ROOT = Path(__file__).resolve().parent.parent
SESSION = {
    "classification": "NON_FORMAL_LIVE_DEMO",
    "session_id": "20260831-081",
    "task_instance_id": "LIVE-TASK-20260831-081",
    "incident_instance_id": "LIVE-INCIDENT-20260831-081",
    "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-081",
}


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class MatrixObserverTests(unittest.TestCase):
    def _bound_event(
        self,
        event_id: str,
        *,
        kind: str = "rca_to_planner",
        event_type: str = "m.room.message",
        include_run: bool = True,
    ) -> dict:
        bindings = [
            SESSION["session_id"],
            SESSION["task_instance_id"],
            SESSION["incident_instance_id"],
        ]
        if include_run:
            bindings.append(SESSION["run_id"])
        return {
            "type": event_type,
            "event_id": event_id,
            "sender": "@worker:example.invalid",
            "origin_server_ts": 1788152400000,
            "content": {
                "msgtype": "m.text",
                "body": " ".join(bindings) + f" LABOPS_EVENT_KIND: {kind}",
                "labops_event": {
                    "kind": kind,
                    "workflow_from": "DIAGNOSIS_READY",
                    "workflow_to": "PLANNING",
                    "artifact_refs": ["shared/hypotheses.json", "C:/private/secret.txt"],
                    "hash_refs": ["a" * 64],
                },
            },
        }

    @staticmethod
    def _sync_payload(rooms: dict) -> dict:
        return {"next_batch": "s123_456", "rooms": {"join": rooms}}

    def test_room_map_loads_only_canonical_unique_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            document = {
                "schema_version": "1.0",
                "rooms": {
                    "!manager:example.invalid": "labops-manager",
                    "!collector:example.invalid": "evidence-collector",
                },
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(load_room_map(path), document["rooms"])
            validate_document(document, "reviewer_config.schema.json", ROOT)

            document["rooms"]["!manager-copy:example.invalid"] = "labops-manager"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_room_map(path)

            document["rooms"] = {"not-a-room": "seventh-agent"}
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_room_map(path)

    def test_normalization_excludes_unlisted_rooms_and_unbound_messages(self) -> None:
        allowed = "!rca:example.invalid"
        excluded = "!unlisted:example.invalid"
        payload = self._sync_payload({
            allowed: {"timeline": {"events": [
                self._bound_event("$accepted"),
                self._bound_event("$missing-run", include_run=False),
            ]}},
            excluded: {"timeline": {"events": [self._bound_event("$excluded")]}}
        })
        events = normalize_sync_response(payload, {allowed: "rca-analyst"}, SESSION)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_id"], "$accepted")
        self.assertEqual(event["actor"], "rca-analyst")
        self.assertEqual(event["kind"], "rca_to_planner")
        self.assertEqual(event["classification"], "NON_AUTHORITATIVE_UI_PROJECTION")
        self.assertEqual(event["artifact_refs"], ["shared/hypotheses.json"])
        self.assertNotIn("body", event)
        self.assertNotIn("private", json.dumps(event))

    def test_normalization_rejects_unknown_event_kind_and_invalid_event_id(self) -> None:
        room = "!planner:example.invalid"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event("not-a-matrix-event", kind="policy_passed"),
                self._bound_event("$unknown", kind="invented_success"),
            ]}}
        })
        self.assertEqual(normalize_sync_response(payload, {room: "experiment-planner"}, SESSION), [])

    def test_sync_once_uses_bearer_header_and_returns_sanitized_snapshot(self) -> None:
        room = "!rca:example.invalid"
        payload = self._sync_payload({
            room: {"timeline": {"events": [self._bound_event("$accepted")]}}
        })
        observed = {}

        def opener(request, timeout):
            observed["url"] = request.full_url
            observed["authorization"] = request.get_header("Authorization")
            observed["timeout"] = timeout
            return FakeResponse(payload)

        result = sync_once(
            "http://matrix.example.invalid:18080",
            "secret-token-value",
            {room: "rca-analyst"},
            since="batch with spaces",
            session=SESSION,
            opener=opener,
        )
        self.assertTrue(result["connected"])
        self.assertEqual(result["source_status"], "LIVE")
        self.assertEqual(result["next_batch"], "s123_456")
        self.assertEqual(len(result["events"]), 1)
        self.assertIn("since=batch+with+spaces", observed["url"])
        self.assertEqual(observed["authorization"], "Bearer secret-token-value")
        self.assertEqual(observed["timeout"], 5.0)
        self.assertNotIn("secret-token-value", json.dumps(result))

    def test_sync_errors_are_structured_and_never_leak_token(self) -> None:
        token = "top-secret-matrix-token"

        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, f"invalid {token}", {}, io.BytesIO())

        result = sync_once(
            "http://matrix.example.invalid",
            token,
            {"!manager:example.invalid": "labops-manager"},
            opener=opener,
        )
        self.assertFalse(result["connected"])
        self.assertEqual(result["source_status"], "DISCONNECTED")
        self.assertEqual(result["errors"], [{"code": "MATRIX_AUTH_FAILED"}])
        self.assertNotIn(token, json.dumps(result))

    def test_encrypted_room_is_explicitly_unsupported(self) -> None:
        room = "!auditor:example.invalid"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event("$encrypted", event_type="m.room.encrypted"),
            ]}}
        })

        def opener(_request, timeout):
            del timeout
            return FakeResponse(payload)

        result = sync_once(
            "http://matrix.example.invalid",
            "secret",
            {room: "verification-auditor"},
            session=SESSION,
            opener=opener,
        )
        self.assertTrue(result["connected"])
        self.assertEqual(result["source_status"], "UNSUPPORTED_ENCRYPTED_ROOM")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["errors"], [{"code": "UNSUPPORTED_ENCRYPTED_ROOM", "room_id": room}])
        self.assertNotIn("body", json.dumps(result))

    def test_projection_write_is_atomic_deduplicated_and_outside_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = Path(prepare_session(ROOT, sessions, "20260831-081")["session_root"])
            snapshot = {
                "connected": True,
                "source_status": "LIVE",
                "checked_at": "2026-08-31T10:00:00Z",
                "last_success_at": "2026-08-31T10:00:00Z",
                "next_batch": "s1",
                "events": [{
                    "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
                    "event_id": "$one",
                    "room_id": "!manager:example.invalid",
                    "actor": "labops-manager",
                    "kind": "task_dispatched",
                    "timestamp": "2026-08-31T10:00:00Z",
                    "workflow_from": "RECEIVED",
                    "workflow_to": "EVIDENCE_COLLECTING",
                    "evidence_state": "OBSERVED",
                    "artifact_refs": [],
                    "hash_refs": [],
                    "raw_body": "must-not-be-written",
                }],
                "errors": [{"code": "MATRIX_UNAVAILABLE", "detail": "must-not-be-written"}],
            }
            write_observer_projection(session_root, snapshot)
            write_observer_projection(session_root, snapshot)
            status = json.loads((session_root / "observer" / "source_status.json").read_text(encoding="utf-8"))
            lines = (session_root / "observer" / "normalized_events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(status["classification"], "NON_AUTHORITATIVE_UI_PROJECTION")
            self.assertEqual(status["errors"], [{"code": "MATRIX_UNAVAILABLE"}])
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["event_id"], "$one")
            cache_text = "\n".join(
                path.read_text(encoding="utf-8") for path in (session_root / "observer").iterdir()
            )
            self.assertNotIn("must-not-be-written", cache_text)
            self.assertEqual(list((session_root / "evidence").iterdir()), [])
            self.assertFalse(any(path.name.endswith(".tmp") for path in (session_root / "observer").iterdir()))

            invalid = dict(snapshot)
            invalid["source_status"] = "PRETEND_LIVE"
            with self.assertRaises(ValueError):
                write_observer_projection(session_root, invalid)

    def test_projection_refuses_formal_evidence_like_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(tmp) / "output-agentteams-at004" / "20260831-081"
            session_root.mkdir(parents=True)
            (session_root / "session.json").write_text(json.dumps(SESSION), encoding="utf-8")
            with self.assertRaises(ValueError):
                write_observer_projection(session_root, {"events": []})

    def test_local_real_room_map_is_gitignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("config/reviewer-room-map.json", ignored)


if __name__ == "__main__":
    unittest.main(verbosity=2)
