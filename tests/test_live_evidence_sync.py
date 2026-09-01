from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from labops.live_demo import EVIDENCE_FILES, HANDOFFS, prepare_session
from labops.live_evidence_sync import (
    DirectoryEvidenceSource,
    SnapshotLimits,
    sync_live_evidence,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class LiveEvidenceSyncTests(unittest.TestCase):
    def _complete_remote_tree(
        self,
        remote: Path,
        session_id: str,
        *,
        complete_verification: bool = True,
    ) -> dict:
        sequence = session_id.rsplit("-", 1)[-1]
        run_id = f"RUN-LABOPS-AT-004-AGENTTEAMS-{sequence}"
        bindings = {
            "session_id": session_id,
            "task_instance_id": f"LIVE-TASK-{session_id}",
            "incident_instance_id": f"LIVE-INCIDENT-{session_id}",
            "attempt_id": f"LIVE-ATTEMPT-{session_id}-01",
            "run_id": run_id,
        }
        source = remote / session_id
        artifact_root = source / "artifacts" / "DEMO-EVAL-DRIFT-004"
        run_root = source / "runs" / run_id
        verification_root = source / "verification"
        artifact_root.mkdir(parents=True)
        run_root.mkdir(parents=True)
        verification_root.mkdir(parents=True)

        def write(path: Path, value: object) -> None:
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        write(artifact_root / "approval_grant.json", {"run_id": run_id})
        write(
            run_root / "gateway_request.json",
            {"experiment_plan": {"live_context": bindings}},
        )
        write(run_root / "gateway_response.json", {"run_id": run_id})
        write(run_root / "run_result.json", {"run_id": run_id})
        write(run_root / "metrics.json", {"candidate_accuracy_values": [0.978125]})
        write(run_root / "artifact_manifest.json", {"run_id": run_id})
        (run_root / "stdout.log").write_text("runner output", encoding="utf-8")
        (run_root / "stderr.log").write_text("", encoding="utf-8")
        verification = {**bindings, "checks": {"runner": True}}
        if complete_verification:
            verification.update(
                {
                    "decision": "PASS",
                    "verified_by": "verification-auditor",
                    "resolution_status": "RESOLVED",
                }
            )
        write(verification_root / "verification_report.json", verification)
        (source / "trace.jsonl").write_text(
            json.dumps({"run_id": run_id}) + "\n", encoding="utf-8"
        )
        return bindings

    @staticmethod
    def _six_handoff_snapshot(bindings: dict) -> dict:
        kinds = (
            "manager_to_collector",
            "collector_to_rca",
            "rca_to_planner",
            "approval_pending",
            "executor_to_auditor",
            "verification_completed",
        )
        events = []
        for index, ((source, _target), kind) in enumerate(zip(HANDOFFS, kinds), 1):
            events.append(
                {
                    **bindings,
                    "validation_version": "matrix-sender-bound-v1",
                    "event_id": f"$handoff-{index}",
                    "room_id": f"!room-{index}:example.org",
                    "actor": source,
                    "kind": kind,
                    "timestamp": f"2026-09-02T00:00:0{index}Z",
                    "artifact_refs": [
                        f"handoff/{index}/input.json",
                        f"handoff/{index}/output.json",
                    ],
                }
            )
        return {"events": events}

    def test_partial_snapshot_is_mirrored_but_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            remote = root / "remote"
            session_id = "20260902-002"
            prepare_session(repo_root(), sessions, session_id)
            source = remote / session_id
            (source / "runs" / "RUN-LABOPS-AT-004-AGENTTEAMS-002").mkdir(
                parents=True
            )
            (source / "verification").mkdir()
            (source / "incident_packet.json").write_text(
                json.dumps({"session_id": session_id}), encoding="utf-8"
            )
            (
                source
                / "runs"
                / "RUN-LABOPS-AT-004-AGENTTEAMS-002"
                / "stdout.log"
            ).write_text("partial runner output", encoding="utf-8")
            (source / "verification" / "verification_report.json").write_text(
                json.dumps({"decision": "PASS"}), encoding="utf-8"
            )

            result = sync_live_evidence(
                repo_root(),
                sessions,
                session_id,
                DirectoryEvidenceSource(remote),
                {"events": []},
                datetime(2026, 9, 2, tzinfo=timezone.utc),
            )

            session = sessions / session_id
            mirror = session / "observer" / "evidence-mirror"
            self.assertEqual(result["status"], "MIRRORED")
            self.assertFalse(result["published"])
            self.assertEqual(result["errors"], ["EVIDENCE_INCOMPLETE"])
            self.assertTrue((mirror / "manifest.json").is_file())
            self.assertTrue((mirror / "incident_packet.json").is_file())
            self.assertFalse((session / "evidence" / "verification.json").exists())
            manifest = json.loads(
                (mirror / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(manifest), {"files"})
            self.assertEqual(
                set(manifest["files"][0]), {"path", "size", "sha256"}
            )

    def test_rejected_path_preserves_previous_successful_mirror(self) -> None:
        class OutOfRootSource:
            limits = SnapshotLimits()

            @staticmethod
            def snapshot(_session_id: str, destination: Path) -> Path:
                return destination.parent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            remote = root / "remote"
            session_id = "20260902-002"
            prepare_session(repo_root(), sessions, session_id)
            (remote / session_id).mkdir(parents=True)
            (remote / session_id / "first.json").write_text(
                "{}", encoding="utf-8"
            )
            now = datetime(2026, 9, 2, tzinfo=timezone.utc)
            sync_live_evidence(
                repo_root(), sessions, session_id,
                DirectoryEvidenceSource(remote), {"events": []}, now,
            )
            manifest_path = (
                sessions / session_id / "observer" / "evidence-mirror" / "manifest.json"
            )
            previous = manifest_path.read_bytes()

            result = sync_live_evidence(
                repo_root(), sessions, session_id,
                OutOfRootSource(), {"events": []}, now,
            )

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["errors"], ["EVIDENCE_PATH_REJECTED"])
            self.assertEqual(manifest_path.read_bytes(), previous)

    def test_oversized_snapshot_preserves_previous_successful_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            remote = root / "remote"
            session_id = "20260902-002"
            prepare_session(repo_root(), sessions, session_id)
            source = remote / session_id
            source.mkdir(parents=True)
            artifact = source / "artifact.bin"
            artifact.write_bytes(b"ok")
            now = datetime(2026, 9, 2, tzinfo=timezone.utc)
            sync_live_evidence(
                repo_root(), sessions, session_id,
                DirectoryEvidenceSource(remote), {"events": []}, now,
            )
            manifest_path = (
                sessions / session_id / "observer" / "evidence-mirror" / "manifest.json"
            )
            previous = manifest_path.read_bytes()
            artifact.write_bytes(b"12345")

            result = sync_live_evidence(
                repo_root(), sessions, session_id,
                DirectoryEvidenceSource(
                    remote,
                    SnapshotLimits(max_file_bytes=4, max_total_bytes=8, max_files=2),
                ),
                {"events": []},
                now,
            )

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["errors"], ["EVIDENCE_SNAPSHOT_TOO_LARGE"])
            self.assertEqual(manifest_path.read_bytes(), previous)

    def test_complete_snapshot_is_promoted_only_after_verifier_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            remote = root / "remote"
            session_id = "20260902-002"
            prepare_session(repo_root(), sessions, session_id)
            bindings = self._complete_remote_tree(remote, session_id)

            def verified(_project: Path, candidate_sessions: Path, candidate_id: str) -> dict:
                candidate = candidate_sessions / candidate_id / "evidence"
                self.assertEqual(candidate_id, session_id)
                for relative in EVIDENCE_FILES:
                    self.assertTrue((candidate / relative).is_file(), relative)
                return {"status": "VERIFIED", "errors": []}

            with patch(
                "labops.live_evidence_sync.verify_session", side_effect=verified
            ):
                result = sync_live_evidence(
                    repo_root(),
                    sessions,
                    session_id,
                    DirectoryEvidenceSource(remote),
                    self._six_handoff_snapshot(bindings),
                    datetime(2026, 9, 2, tzinfo=timezone.utc),
                )

            evidence = sessions / session_id / "evidence"
            self.assertEqual(result["status"], "VERIFIED")
            self.assertTrue(result["published"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(
                set(EVIDENCE_FILES),
                {
                    path.relative_to(evidence).as_posix()
                    for path in evidence.rglob("*")
                    if path.is_file()
                },
            )

    def test_invalid_verification_stays_in_mirror_and_is_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            remote = root / "remote"
            session_id = "20260902-002"
            prepare_session(repo_root(), sessions, session_id)
            bindings = self._complete_remote_tree(
                remote, session_id, complete_verification=False
            )

            result = sync_live_evidence(
                repo_root(),
                sessions,
                session_id,
                DirectoryEvidenceSource(remote),
                self._six_handoff_snapshot(bindings),
                datetime(2026, 9, 2, tzinfo=timezone.utc),
            )

            session = sessions / session_id
            self.assertTrue(
                (
                    session
                    / "observer"
                    / "evidence-mirror"
                    / "verification"
                    / "verification_report.json"
                ).is_file()
            )
            self.assertFalse((session / "evidence" / "verification.json").exists())
            self.assertFalse(result["published"])
            self.assertIn(
                result["errors"][0],
                {"EVIDENCE_SCHEMA_INVALID", "EVIDENCE_INCOMPLETE"},
            )
            self.assertNotIn(str(remote), json.dumps(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
