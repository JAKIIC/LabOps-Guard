"""LabOps Guard unit tests (standard library unittest).

Covers the 8 required scenarios:
  1. no evidence_id -> refuse diagnosis
  2. approval rejected
  3. forbidden action
  4. out-of-boundary path
  5. simulated action
  6. verification failure
  7. trace hash chain
  8. synthetic compatibility demo end-to-end
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from labops import registry, evidence, diagnosis, approval, action, verify, trace as trace_mod
from labops import demo as demo_mod
from labops.cli import main as cli_main


# --- portable fixtures resolver (REV-2: no hardcoded /root paths) ---

def repo_root() -> Path:
    """Repo root = parent of the tests/ directory."""
    return Path(__file__).resolve().parent.parent


def fixtures_dir() -> Path:
    """demo/fixtures dir, overridable via env LABOPS_FIXTURES."""
    env = os.environ.get("LABOPS_FIXTURES")
    if env:
        return Path(env).resolve()
    return repo_root() / "demo" / "fixtures"


def fixture_snapshot() -> Path:
    return fixtures_dir() / "project_snapshot_synthetic"


def fixture_audit() -> Path:
    return fixtures_dir() / "synthetic_audit"


def fixture_verification() -> Path:
    return fixtures_dir() / "synthetic_snapshot_verification.json"


def fixture_allowed_list() -> Path:
    return repo_root() / "demo" / "synthetic_allowed_files.json"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir()
        self.trace = trace_mod.TraceLog(self.ws / "trace.jsonl")

    def tearDown(self):
        self.tmp.cleanup()


class TestNoEvidenceDiagnosis(Base):
    def test_hypothesis_without_evidence_rejected(self):
        with self.assertRaises(diagnosis.NoEvidenceError):
            diagnosis.build_hypothesis("H-X", "claim", [])
        with self.assertRaises(diagnosis.NoEvidenceError):
            diagnosis.build_hypothesis("H-Y", "claim", None)

    def test_unknown_hypothesis_is_explicit(self):
        h = diagnosis.unknown_hypothesis("H-U", "c", "no evidence")
        self.assertEqual(h["state"], "UNKNOWN")
        self.assertEqual(h["evidence_ids"], [])


class TestApprovalRejected(Base):
    def test_reject_is_first_class_and_blocks_execution(self):
        approval.create_approval("A-1", "H-1", "A-1", "pip install x",
                                 approval.MANUAL_APPROVAL, self.ws, trace=self.trace)
        approval.decide("A-1", "reject", self.ws, trace=self.trace)
        self.assertFalse(approval.is_approved("A-1", self.ws))
        reqs = approval.load_approvals(self.ws)
        self.assertEqual(reqs[0]["status"], "REJECTED")

    def test_approval_timeout_is_first_class(self):
        approval.create_approval("A-2", "H-2", "A-2", "pip install x",
                                 approval.MANUAL_APPROVAL, self.ws, trace=self.trace)
        approval.mark_timeout("A-2", self.ws, trace=self.trace)
        self.assertEqual(approval.load_approvals(self.ws)[0]["status"], "TIMEOUT")


class TestApprovalRequestCLI(Base):
    def test_manual_request_is_created(self):
        rc = cli_main([
            "approve", "request", "--workspace", str(self.ws),
            "--approval-id", "APR-1", "--hypothesis-id", "H-1",
            "--action-id", "A-1", "--command", "pip install numpy",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(approval.load_approvals(self.ws)[0]["status"], "PENDING")

    def test_forbidden_request_is_refused(self):
        rc = cli_main([
            "approve", "request", "--workspace", str(self.ws),
            "--approval-id", "APR-F", "--hypothesis-id", "H-F",
            "--action-id", "A-F", "--command", "read test_codeword_x_private.csv",
        ])
        self.assertEqual(rc, 2)
        self.assertEqual(approval.load_approvals(self.ws), [])


class TestForbiddenAction(Base):
    def test_forbidden_action_refused_even_if_approved(self):
        with self.assertRaises(PermissionError):
            action.execute_action("A-F", "read test_codeword_x_private.csv",
                                  self.ws, dry_run=False, trace=self.trace)
        with self.assertRaises(PermissionError):
            action.execute_action("A-F2", "sudo rm -rf /", self.ws,
                                  dry_run=False, trace=self.trace)

    def test_forbidden_classification(self):
        self.assertEqual(approval.classify_action("x", "read train_noisy_y_shard_000.csv"),
                         approval.FORBIDDEN)


class TestBoundary(Base):
    def test_out_of_boundary_workdir_rejected(self):
        with self.assertRaises(PermissionError):
            action.execute_action("A-B", "echo hi", self.ws,
                                  workdir="/etc", dry_run=True, trace=self.trace)

    def test_out_of_boundary_write_rejected(self):
        with self.assertRaises(PermissionError):
            action.write_output_file("/tmp/evil.txt", "x", self.ws,
                                     dry_run=False, trace=self.trace)


class TestSimulatedAction(Base):
    def test_risky_action_simulated_not_executed(self):
        r = action.execute_action("A-S", "pip install numpy pandas",
                                  self.ws, dry_run=False, trace=self.trace)
        self.assertTrue(r.simulated)
        self.assertEqual(r.status, "SUCCEEDED")
        self.assertIn("SIMULATED", r.output)

    def test_dry_run_default(self):
        r = action.execute_action("A-D", "echo hello", self.ws,
                                  dry_run=True, trace=self.trace)
        self.assertEqual(r.status, "DRY_RUN")
        self.assertIn("dry-run", r.output)


class TestVerificationFailure(Base):
    def test_failed_action_does_not_close(self):
        v = verify.verify_action({"status": "FAILED"}, self.ws, trace=self.trace)
        self.assertNotEqual(v["status"], "PASSED")
        self.assertEqual(v["incident_state"], verify.BLOCKED)

    def test_missing_artifact_fails(self):
        v = verify.verify_action({"status": "SUCCEEDED"}, self.ws,
                                 expected_artifact=str(self.ws / "nope.txt"),
                                 trace=self.trace)
        self.assertEqual(v["status"], "FAILED")
        self.assertEqual(v["incident_state"], verify.BLOCKED)

    def test_dry_run_simulated_never_closes(self):
        # REV-1: dry-run/simulated must NOT close, even with postcondition
        target = self.ws / "artifact.txt"
        target.write_text("x", encoding="utf-8")
        v = verify.verify_action({"status": "SUCCEEDED", "simulated": True}, self.ws,
                                 expected_artifact=str(target), trace=self.trace)
        self.assertNotEqual(v["incident_state"], verify.CLOSED)
        self.assertFalse(v["underlying_issue_resolved"])
        self.assertEqual(v["demo_verification"], "PASSED")

    def test_agentteams_nested_result_is_supported(self):
        v = verify.verify_action(
            {"result": {"status": "SUCCEEDED", "simulated": True, "dry_run": True}},
            self.ws,
            trace=self.trace,
        )
        self.assertEqual(v["status"], "PASSED")
        self.assertEqual(v["incident_state"], verify.DEMO_PASSED_NOT_RESOLVED)
        self.assertFalse(v["underlying_issue_resolved"])

    def test_no_postcondition_never_closes(self):
        v = verify.verify_action({"status": "SUCCEEDED", "simulated": False}, self.ws,
                                 expected_artifact=None, trace=self.trace)
        self.assertNotEqual(v["incident_state"], verify.CLOSED)
        self.assertFalse(v["has_postcondition"])

    def test_real_action_with_postcondition_closes(self):
        target = self.ws / "artifact.txt"
        target.write_text("hello", encoding="utf-8")
        v = verify.verify_action({"status": "SUCCEEDED", "simulated": False}, self.ws,
                                 expected_artifact=str(target), trace=self.trace)
        self.assertEqual(v["incident_state"], verify.CLOSED)
        self.assertTrue(v["underlying_issue_resolved"])

    def test_expected_artifact_outside_workspace_rejected(self):
        v = verify.verify_action({"status": "SUCCEEDED", "simulated": False}, self.ws,
                                 expected_artifact="/etc/passwd", trace=self.trace)
        self.assertNotEqual(v["incident_state"], verify.CLOSED)
        self.assertFalse(all(c["passed"] for c in v["checks"]))


class TestPathSafety(Base):
    def test_path_traversal_rejected(self):
        snap = Path(self.tmp.name) / "snap"
        snap.mkdir()
        (snap / "ok.txt").write_text("ok", encoding="utf-8")
        outside = Path(self.tmp.name) / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        rec = registry.register_snapshot(snap, ["../secret.txt", "ok.txt"], self.ws, trace=self.trace)
        # traversal entry refused; ok.txt hashed
        refused_paths = [r["path"] for r in rec["refused"]]
        self.assertIn("../secret.txt", refused_paths)
        hashed = [e["path"] for e in rec["entries"] if e["present"]]
        self.assertIn("ok.txt", hashed)
        self.assertNotIn("../secret.txt", hashed)

    def test_excluded_marker_rejected(self):
        snap = Path(self.tmp.name) / "snap"
        snap.mkdir()
        (snap / "train_noisy_y_shard_000.csv").write_text("x", encoding="utf-8")
        (snap / "m.pem").write_text("k", encoding="utf-8")
        rec = registry.register_snapshot(snap, ["train_noisy_y_shard_000.csv", "m.pem"],
                                         self.ws, trace=self.trace)
        self.assertEqual(len(rec["refused"]), 2)
        self.assertTrue(all(e["refused"] for e in rec["entries"]))

    def test_registry_absolute_path_escape_rejected(self):
        snap = Path(self.tmp.name) / "snap"
        snap.mkdir()
        rec = registry.register_snapshot(snap, [str(Path(self.tmp.name) / "outside.txt")],
                                         self.ws, trace=self.trace)
        self.assertEqual(len(rec["refused"]), 1)


class TestPolicyDowngrade(Base):
    def test_downgrade_forbidden_to_readonly_rejected(self):
        with self.assertRaises(approval.PolicyDowngradeError):
            approval.classify_action("A", "read test_codeword_x_private.csv",
                                     approval.READ_ONLY_AUTO)

    def test_downgrade_manual_to_readonly_rejected(self):
        with self.assertRaises(approval.PolicyDowngradeError):
            approval.classify_action("A", "pip install numpy", approval.READ_ONLY_AUTO)

    def test_same_or_stricter_allowed(self):
        self.assertEqual(approval.classify_action("A", "pip install x", approval.MANUAL_APPROVAL),
                         approval.MANUAL_APPROVAL)
        self.assertEqual(approval.classify_action("A", "pip install x", approval.FORBIDDEN),
                         approval.FORBIDDEN)


class TestGap007EvidenceId(Base):
    def test_gap007_has_evidence_id(self):
        gaps = [{"gap_id": "GAP-007", "category": "runtime", "title": "BER not verifiable"}]
        rec = diagnosis.diagnose_from_gaps(gaps, self.ws, trace=self.trace)
        h = rec["hypotheses"][0]
        self.assertEqual(h["state"], "UNKNOWN")
        self.assertIn("GAP-007", h["evidence_ids"])
        self.assertTrue(h["block_reason"])


class TestTraceHashChain(Base):
    def test_chain_verifies(self):
        self.trace.append("incident", "i1", "a")
        self.trace.append("approval", "A1", "b", from_state="P", to_state="Q")
        self.trace.append("action", "act", "c")
        ok, msg = self.trace.verify_chain()
        self.assertTrue(ok, msg)

    def test_tamper_breaks_chain(self):
        self.trace.append("incident", "i1", "a")
        self.trace.append("action", "act", "b")
        p = self.ws / "trace.jsonl"
        content = p.read_text(encoding="utf-8").splitlines()
        # tamper first line
        rec = json.loads(content[0])
        rec["event"] = "tampered"
        content[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        p.write_text("\n".join(content) + "\n", encoding="utf-8")
        ok, _ = self.trace.verify_chain()
        self.assertFalse(ok)


class TestSyntheticCompatibilityDemo(Base):
    def test_synthetic_demo_end_to_end(self):
        snapshot = fixture_snapshot()
        audit = fixture_audit()
        verif = fixture_verification()
        allowed = fixture_allowed_list()
        ws = self.ws / "demo"
        rc = demo_mod.run_demo(workspace=ws, snapshot_dir=snapshot,
                               audit_dir=audit, verification_json=verif,
                               allowed_list=allowed, trace=self.trace)
        self.assertEqual(rc, 0)
        # registry has 13 files, VERIFIED, no mismatches
        reg = json.loads((ws / "registry_record.json").read_text(encoding="utf-8"))
        self.assertEqual(reg["allowed_file_count"], 13)
        self.assertEqual(reg["verification_status"], "VERIFIED")
        self.assertEqual(reg["hash_mismatches_vs_verification"], [])
        # diagnosis has 10 hypotheses, all with state in allowed set
        diag = json.loads((ws / "diagnosis_candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(diag["hypothesis_count"], 10)
        states = {h["state"] for h in diag["hypotheses"]}
        self.assertTrue(states <= {"BLOCKED", "UNKNOWN", "FORBIDDEN", "CANDIDATE"})
        # chain ok
        ok, msg = self.trace.verify_chain()
        self.assertTrue(ok, msg)
        # REV-1 closure semantics: demo must NOT be CLOSED
        v = json.loads((ws / "verification_result.json").read_text(encoding="utf-8"))
        self.assertEqual(v["demo_verification"], "PASSED")
        self.assertNotEqual(v["incident_state"], "CLOSED")
        self.assertFalse(v["underlying_issue_resolved"])


class TestPortability(Base):
    """No host-root hardcoding; synthetic fixture 13/13 VERIFIED; 0 excluded files."""

    def _walk_source_files(self):
        root = repo_root()
        exts = (".py", ".sh", ".ps1")
        return [p for p in root.rglob("*") if p.is_file() and p.suffix in exts
                and "fixtures" not in p.parts]

    def test_no_root_hardcoded(self):
        forbidden = "/" + "root" + "/hiclaw-fs"  # built dynamically so the
        # forbidden path literal is not itself present in this source file
        offending = []
        for p in self._walk_source_files():
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            if forbidden in text:
                offending.append(str(p))
        self.assertEqual(offending, [], f"hardcoded {forbidden} in: {offending}")

    def test_fixture_13_verified(self):
        snap = fixture_snapshot()
        verif = json.loads(fixture_verification().read_text(encoding="utf-8"))
        exp = verif["all_allowed_file_sha256"]
        self.assertEqual(len(exp), 13)
        import hashlib
        for rel, h in exp.items():
            f = snap / rel
            self.assertTrue(f.exists(), f"fixture missing {rel}")
            self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), h, f"hash mismatch {rel}")

    def test_fixture_zero_excluded(self):
        from labops.evidence import is_excluded
        snap = fixture_snapshot()
        excluded = [p.relative_to(snap).as_posix() for p in snap.rglob("*") if p.is_file()
                    and is_excluded(p.relative_to(snap).as_posix())]
        self.assertEqual(excluded, [], f"excluded files in fixture: {excluded}")

    def test_allowed_files_match_fixture(self):
        allowed = json.loads(fixture_allowed_list().read_text(encoding="utf-8"))
        snap = fixture_snapshot()
        # as_posix() normalises to forward slashes on every platform (REV-2.1)
        present = sorted(p.relative_to(snap).as_posix() for p in snap.rglob("*") if p.is_file())
        self.assertEqual(sorted(allowed), present)

    def test_windows_separator_semantics(self):
        """REV-2.1: a relative path expressed with backslashes still matches
        the forward-slash entries in allowed_files.json after normalisation."""
        allowed = json.loads(fixture_allowed_list().read_text(encoding="utf-8"))
        # simulate a Windows-style relative path (backslashes)
        windows_style = [p.replace("/", "\\") for p in allowed]
        # as_posix() (and explicit backslash->slash) must normalise to forward slashes
        for w in windows_style:
            self.assertIn(Path(w.replace("\\", "/")).as_posix(), allowed)
        self.assertEqual(sorted(Path(w.replace("\\", "/")).as_posix() for w in windows_style),
                         sorted(allowed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
