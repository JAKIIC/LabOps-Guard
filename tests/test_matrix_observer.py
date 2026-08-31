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
    active_session_binding,
    load_room_map,
    normalize_sync_response,
    probe_joined_rooms,
    sync_once,
    write_observer_projection,
)
from labops.recovery import request_recovery


ROOT = Path(__file__).resolve().parent.parent
SESSION = {
    "classification": "NON_FORMAL_LIVE_DEMO",
    "session_id": "20260831-081",
    "task_instance_id": "LIVE-TASK-20260831-081",
    "incident_instance_id": "LIVE-INCIDENT-20260831-081",
    "attempt_id": "LIVE-ATTEMPT-20260831-081-01",
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
        include_attempt: bool = True,
        sender: str = "@rca-analyst:matrix-local.hiclaw.io",
    ) -> dict:
        bindings = [
            SESSION["session_id"],
            SESSION["task_instance_id"],
            SESSION["incident_instance_id"],
        ]
        if include_attempt:
            bindings.append(SESSION["attempt_id"])
        if include_run:
            bindings.append(SESSION["run_id"])
        return {
            "type": event_type,
            "event_id": event_id,
            "sender": sender,
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
                    "!manager:matrix-local.hiclaw.io": "labops-manager",
                    "!collector:matrix-local.hiclaw.io": "evidence-collector",
                },
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(load_room_map(path), document["rooms"])
            validate_document(document, "reviewer_config.schema.json", ROOT)

            document["rooms"]["!manager-copy:matrix-local.hiclaw.io"] = "labops-manager"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_room_map(path)

            document["rooms"] = {"not-a-room": "seventh-agent"}
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_room_map(path)

    def test_room_map_rejects_the_committed_placeholder_template(self) -> None:
        with self.assertRaisesRegex(ValueError, "placeholder"):
            load_room_map(ROOT / "config/reviewer-room-map.example.json")

    def test_normalization_excludes_unlisted_rooms_and_unbound_messages(self) -> None:
        allowed = "!rca:matrix-local.hiclaw.io"
        excluded = "!unlisted:matrix-local.hiclaw.io"
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
        self.assertEqual(event["validation_version"], "matrix-sender-bound-v1")
        self.assertEqual(event["session_id"], SESSION["session_id"])
        self.assertEqual(event["task_instance_id"], SESSION["task_instance_id"])
        self.assertEqual(event["incident_instance_id"], SESSION["incident_instance_id"])
        self.assertEqual(event["attempt_id"], SESSION["attempt_id"])
        self.assertEqual(event["run_id"], SESSION["run_id"])
        self.assertEqual(event["artifact_refs"], ["shared/hypotheses.json"])
        self.assertNotIn("body", event)
        self.assertNotIn("private", json.dumps(event))

    def test_normalization_rejects_an_event_without_attempt_binding(self) -> None:
        room = "!rca:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event("$missing-attempt", include_attempt=False),
            ]}}
        })

        self.assertEqual(normalize_sync_response(payload, {room: "rca-analyst"}, SESSION), [])

    def test_normalization_rejects_unknown_event_kind_and_invalid_event_id(self) -> None:
        room = "!planner:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event("not-a-matrix-event", kind="policy_passed"),
                self._bound_event("$unknown", kind="invented_success"),
            ]}}
        })
        self.assertEqual(normalize_sync_response(payload, {room: "experiment-planner"}, SESSION), [])

    def test_normalization_observes_evidence_gap_without_treating_it_as_terminal_proof(self) -> None:
        room = "!collector:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event(
                    "$gap",
                    kind="evidence_incomplete",
                    sender="@evidence-collector:matrix-local.hiclaw.io",
                ),
            ]}}
        })

        events = normalize_sync_response(payload, {room: "evidence-collector"}, SESSION)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "evidence_incomplete")
        self.assertEqual(events[0]["evidence_state"], "OBSERVED")
        self.assertNotEqual(events[0]["evidence_state"], "VERIFIED")

    def test_normalization_accepts_a_markdown_wrapped_event_kind_marker(self) -> None:
        room = "!collector:matrix-local.hiclaw.io"
        event = self._bound_event(
            "$markdown-gap",
            kind="evidence_incomplete",
            sender="@evidence-collector:matrix-local.hiclaw.io",
        )
        event["content"].pop("labops_event")
        event["content"]["body"] = (
            " ".join(
                [
                    SESSION["session_id"],
                    SESSION["task_instance_id"],
                    SESSION["incident_instance_id"],
                    SESSION["attempt_id"],
                    SESSION["run_id"],
                ]
            )
            + " **LABOPS_EVENT_KIND:** evidence_incomplete"
        )
        payload = self._sync_payload({room: {"timeline": {"events": [event]}}})

        events = normalize_sync_response(payload, {room: "evidence-collector"}, SESSION)

        self.assertEqual([item["kind"] for item in events], ["evidence_incomplete"])

    def test_normalization_rejects_manager_instruction_in_collector_room(self) -> None:
        room = "!collector:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event(
                    "$manager-instruction",
                    kind="evidence_incomplete",
                    sender="@manager:matrix-local.hiclaw.io",
                ),
            ]}}
        })

        self.assertEqual(
            normalize_sync_response(payload, {room: "evidence-collector"}, SESSION),
            [],
        )

    def test_normalization_rejects_matching_localpart_from_a_foreign_homeserver(self) -> None:
        room = "!collector:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event(
                    "$foreign-collector",
                    kind="evidence_incomplete",
                    sender="@evidence-collector:evil.example",
                ),
            ]}}
        })

        self.assertEqual(
            normalize_sync_response(payload, {room: "evidence-collector"}, SESSION),
            [],
        )

    def test_normalization_accepts_runtime_alias_only_for_its_canonical_role(self) -> None:
        room = "!planner:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            room: {"timeline": {"events": [
                self._bound_event(
                    "$planner-policy",
                    kind="policy_passed",
                    sender="@researcher:matrix-local.hiclaw.io",
                ),
            ]}}
        })

        events = normalize_sync_response(payload, {room: "experiment-planner"}, SESSION)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "experiment-planner")

    def test_human_approval_requires_a_non_agent_sender_on_the_room_homeserver(self) -> None:
        room = "!manager:matrix-local.hiclaw.io"
        local = self._bound_event(
            "$local-approval",
            kind="approval_granted",
            sender="@human-reviewer:matrix-local.hiclaw.io",
        )
        local["content"]["labops_event"]["actor"] = "human-approver"
        foreign = self._bound_event(
            "$foreign-approval",
            kind="approval_granted",
            sender="@human-reviewer:evil.example",
        )
        foreign["content"]["labops_event"]["actor"] = "human-approver"
        payload = self._sync_payload({
            room: {"timeline": {"events": [local, foreign]}},
        })

        events = normalize_sync_response(payload, {room: "labops-manager"}, SESSION)

        self.assertEqual([event["event_id"] for event in events], ["$local-approval"])
        self.assertEqual(events[0]["actor"], "human-approver")

    def test_sync_once_uses_bearer_header_and_returns_sanitized_snapshot(self) -> None:
        room = "!rca:matrix-local.hiclaw.io"
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

    def test_initial_sync_fails_closed_when_configured_rooms_are_not_joined(self) -> None:
        configured = "!collector:matrix-local.hiclaw.io"
        payload = self._sync_payload({
            "!different:matrix-local.hiclaw.io": {"timeline": {"events": []}},
        })

        def opener(_request, timeout):
            del timeout
            return FakeResponse(payload)

        result = sync_once(
            "http://matrix-local.hiclaw.io:18080",
            "secret-token-value",
            {configured: "evidence-collector"},
            session=SESSION,
            opener=opener,
        )

        self.assertFalse(result["connected"])
        self.assertEqual(result["source_status"], "DISCONNECTED")
        self.assertEqual(result["errors"], [{"code": "MATRIX_ROOM_MAP_UNJOINED"}])
        self.assertNotIn(configured, json.dumps(result))

    def test_incremental_sync_does_not_require_unchanged_rooms_to_reappear(self) -> None:
        configured = "!collector:matrix-local.hiclaw.io"

        def opener(_request, timeout):
            del timeout
            return FakeResponse(self._sync_payload({}))

        result = sync_once(
            "http://matrix-local.hiclaw.io:18080",
            "secret-token-value",
            {configured: "evidence-collector"},
            since="s123_456",
            session=SESSION,
            opener=opener,
        )

        self.assertTrue(result["connected"])
        self.assertEqual(result["source_status"], "LIVE")

    def test_incremental_sync_fails_closed_when_a_configured_room_is_left(self) -> None:
        configured = "!collector:matrix-local.hiclaw.io"
        payload = {
            "next_batch": "s124_000",
            "rooms": {"join": {}, "leave": {configured: {}}},
        }

        def opener(_request, timeout):
            del timeout
            return FakeResponse(payload)

        result = sync_once(
            "http://matrix-local.hiclaw.io:18080",
            "secret-token-value",
            {configured: "evidence-collector"},
            since="s123_456",
            session=SESSION,
            opener=opener,
        )

        self.assertFalse(result["connected"])
        self.assertEqual(result["errors"], [{"code": "MATRIX_ROOM_MAP_UNJOINED"}])

    def test_membership_probe_fails_closed_without_leaking_room_ids_or_token(self) -> None:
        configured = "!collector:matrix-local.hiclaw.io"
        token = "secret-token-value"

        def opener(_request, timeout):
            del timeout
            return FakeResponse({"joined_rooms": ["!different:matrix-local.hiclaw.io"]})

        result = probe_joined_rooms(
            "http://matrix-local.hiclaw.io:18080",
            token,
            {configured: "evidence-collector"},
            opener=opener,
        )

        self.assertEqual(
            result,
            {
                "connected": True,
                "all_joined": False,
                "rooms_expected": 1,
                "error": "MATRIX_ROOM_MAP_UNJOINED",
            },
        )
        rendered = json.dumps(result)
        self.assertNotIn(configured, rendered)
        self.assertNotIn(token, rendered)

    def test_sync_errors_are_structured_and_never_leak_token(self) -> None:
        token = "top-secret-matrix-token"

        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, f"invalid {token}", {}, io.BytesIO())

        result = sync_once(
            "http://matrix.example.invalid",
            token,
            {"!manager:matrix-local.hiclaw.io": "labops-manager"},
            opener=opener,
        )
        self.assertFalse(result["connected"])
        self.assertEqual(result["source_status"], "DISCONNECTED")
        self.assertEqual(result["errors"], [{"code": "MATRIX_AUTH_FAILED"}])
        self.assertNotIn(token, json.dumps(result))

    def test_encrypted_room_is_explicitly_unsupported(self) -> None:
        room = "!auditor:matrix-local.hiclaw.io"
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
                    "validation_version": "matrix-sender-bound-v1",
                    "event_id": "$one",
                    "room_id": "!manager:matrix-local.hiclaw.io",
                    "session_id": "20260831-081",
                    "task_instance_id": "LIVE-TASK-20260831-081",
                    "incident_instance_id": "LIVE-INCIDENT-20260831-081",
                    "attempt_id": "LIVE-ATTEMPT-20260831-081-01",
                    "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-081",
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

    def test_projection_discards_legacy_cache_without_sender_validation_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(prepare_session(ROOT, Path(tmp), "20260831-081")["session_root"])
            observer = session_root / "observer"
            observer.mkdir()
            legacy = {
                "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
                "event_id": "$legacy",
                "room_id": "!collector:matrix-local.hiclaw.io",
                "actor": "evidence-collector",
                "kind": "evidence_incomplete",
                "timestamp": "2026-08-31T10:00:00Z",
                "workflow_from": "EVIDENCE_COLLECTING",
                "workflow_to": "BLOCKED",
                "evidence_state": "OBSERVED",
                "artifact_refs": [],
                "hash_refs": [],
            }
            (observer / "normalized_events.jsonl").write_text(
                json.dumps(legacy) + "\n",
                encoding="utf-8",
            )

            write_observer_projection(
                session_root,
                {
                    "connected": True,
                    "source_status": "LIVE",
                    "checked_at": "2026-08-31T10:00:01Z",
                    "last_success_at": "2026-08-31T10:00:01Z",
                    "next_batch": "s1",
                    "events": [],
                    "errors": [],
                },
            )

            self.assertEqual(
                (observer / "normalized_events.jsonl").read_text(encoding="utf-8"),
                "",
            )

    def test_recovery_refreshes_active_binding_and_preserves_prior_attempt_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(prepare_session(ROOT, Path(tmp), "20260831-081")["session_root"])
            initial = dict(SESSION)
            first = {
                "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
                "validation_version": "matrix-sender-bound-v1",
                "event_id": "$attempt-one",
                "room_id": "!collector:matrix-local.hiclaw.io",
                **{name: initial[name] for name in (
                    "session_id", "task_instance_id", "incident_instance_id", "attempt_id", "run_id"
                )},
                "actor": "evidence-collector",
                "kind": "evidence_incomplete",
                "timestamp": "2026-08-31T10:00:00Z",
                "workflow_from": "EVIDENCE_COLLECTING",
                "workflow_to": "BLOCKED",
                "evidence_state": "OBSERVED",
                "artifact_refs": [],
                "hash_refs": [],
            }
            write_observer_projection(session_root, {
                "connected": True,
                "source_status": "LIVE",
                "events": [first],
                "errors": [],
            })
            source = session_root / "evidence" / "recovery-source.json"
            source.write_text("{}\n", encoding="utf-8")
            result = request_recovery(
                session_root,
                failure_type="EVIDENCE_INCOMPLETE",
                requested_by="verification-auditor",
                source_refs=["evidence/recovery-source.json"],
            )

            active = active_session_binding(session_root)
            self.assertEqual(active["attempt_id"], result["attempt"]["attempt_id"])
            self.assertEqual(active["run_id"], result["attempt"]["run_id"])
            second = dict(first)
            second.update({
                "event_id": "$attempt-two",
                "attempt_id": active["attempt_id"],
                "run_id": active["run_id"],
            })
            write_observer_projection(session_root, {
                "connected": True,
                "source_status": "LIVE",
                "events": [second],
                "errors": [],
            })

            records = [
                json.loads(line)
                for line in (session_root / "observer" / "normalized_events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual([record["event_id"] for record in records], ["$attempt-one", "$attempt-two"])
            self.assertEqual(records[0]["attempt_id"], SESSION["attempt_id"])
            self.assertEqual(records[1]["attempt_id"], active["attempt_id"])

    def test_projection_rejects_unknown_attempt_after_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(prepare_session(ROOT, Path(tmp), "20260831-081")["session_root"])
            source = session_root / "evidence" / "recovery-source.json"
            source.write_text("{}\n", encoding="utf-8")
            request_recovery(
                session_root,
                failure_type="EVIDENCE_INCOMPLETE",
                requested_by="verification-auditor",
                source_refs=["evidence/recovery-source.json"],
            )
            unknown = {
                "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
                "validation_version": "matrix-sender-bound-v1",
                "event_id": "$unknown-attempt",
                "room_id": "!collector:matrix-local.hiclaw.io",
                "session_id": SESSION["session_id"],
                "task_instance_id": SESSION["task_instance_id"],
                "incident_instance_id": SESSION["incident_instance_id"],
                "attempt_id": "LIVE-ATTEMPT-20260831-081-99",
                "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-999",
                "actor": "evidence-collector",
                "kind": "evidence_incomplete",
                "evidence_state": "OBSERVED",
                "artifact_refs": [],
                "hash_refs": [],
            }
            write_observer_projection(session_root, {
                "connected": True,
                "source_status": "LIVE",
                "events": [unknown],
                "errors": [],
            })
            self.assertEqual(
                (session_root / "observer" / "normalized_events.jsonl").read_text(encoding="utf-8"),
                "",
            )

    def test_projection_rejects_new_events_from_an_old_attempt_after_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(prepare_session(ROOT, Path(tmp), "20260831-081")["session_root"])
            source = session_root / "evidence" / "recovery-source.json"
            source.write_text("{}\n", encoding="utf-8")
            request_recovery(
                session_root,
                failure_type="EVIDENCE_INCOMPLETE",
                requested_by="verification-auditor",
                source_refs=["evidence/recovery-source.json"],
            )
            stale = {
                "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
                "validation_version": "matrix-sender-bound-v1",
                "event_id": "$late-old-attempt",
                "room_id": "!collector:matrix-local.hiclaw.io",
                **{name: SESSION[name] for name in (
                    "session_id", "task_instance_id", "incident_instance_id", "attempt_id", "run_id"
                )},
                "actor": "evidence-collector",
                "kind": "evidence_incomplete",
                "evidence_state": "OBSERVED",
                "artifact_refs": [],
                "hash_refs": [],
            }

            write_observer_projection(session_root, {
                "connected": True,
                "source_status": "LIVE",
                "events": [stale],
                "errors": [],
            })

            self.assertEqual(
                (session_root / "observer" / "normalized_events.jsonl").read_text(encoding="utf-8"),
                "",
            )

    def test_corrupt_recovery_trace_forces_source_status_disconnected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(prepare_session(ROOT, Path(tmp), "20260831-081")["session_root"])
            write_observer_projection(session_root, {
                "connected": True,
                "source_status": "LIVE",
                "checked_at": "2026-08-31T10:00:00Z",
                "last_success_at": "2026-08-31T10:00:00Z",
                "events": [],
                "errors": [],
            })
            recovery = session_root / "recovery"
            recovery.mkdir()
            (recovery / "recovery_trace.jsonl").write_text("not-json\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "recovery"):
                write_observer_projection(session_root, {
                    "connected": True,
                    "source_status": "LIVE",
                    "checked_at": "2026-08-31T10:00:01Z",
                    "last_success_at": "2026-08-31T10:00:01Z",
                    "events": [],
                    "errors": [],
                })

            status = json.loads(
                (session_root / "observer" / "source_status.json").read_text(encoding="utf-8")
            )
            self.assertFalse(status["connected"])
            self.assertEqual(status["source_status"], "DISCONNECTED")
            self.assertEqual(status["errors"], [{"code": "RECOVERY_BINDING_INVALID"}])

    def test_normalization_uses_latest_recovery_attempt_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_root = Path(prepare_session(ROOT, Path(tmp), "20260831-081")["session_root"])
            source = session_root / "evidence" / "recovery-source.json"
            source.write_text("{}\n", encoding="utf-8")
            request_recovery(
                session_root,
                failure_type="EVIDENCE_INCOMPLETE",
                requested_by="verification-auditor",
                source_refs=["evidence/recovery-source.json"],
            )
            active = active_session_binding(session_root)
            event = self._bound_event(
                "$latest-attempt",
                kind="evidence_incomplete",
                sender="@evidence-collector:matrix-local.hiclaw.io",
            )
            body = event["content"]["body"]
            event["content"]["body"] = body.replace(
                SESSION["attempt_id"], active["attempt_id"]
            ).replace(SESSION["run_id"], active["run_id"])
            payload = self._sync_payload({
                "!collector:matrix-local.hiclaw.io": {"timeline": {"events": [event]}}
            })

            events = normalize_sync_response(
                payload,
                {"!collector:matrix-local.hiclaw.io": "evidence-collector"},
                active,
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["attempt_id"], active["attempt_id"])
            self.assertEqual(events[0]["run_id"], active["run_id"])

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
