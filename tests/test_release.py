import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.verify_evidence import verify_bundle, verify_trace


class TestReleaseEvidenceVerifier(unittest.TestCase):
    def test_trace_hash_chain(self):
        previous = None
        lines = []
        for seq in range(2):
            record = {"seq": seq, "event": "test", "prev_hash": previous}
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
            record["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
            previous = record["hash"]
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        ok, message = verify_trace(("\n".join(lines) + "\n").encode())
        self.assertTrue(ok, message)

    def test_bundle_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("proof.txt", b"proof")
            manifest = {
                "task_id": "unexpected",
                "zip_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "artifacts": {"proof.txt": hashlib.sha256(b"tampered expectation").hexdigest()},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = verify_bundle(bundle, manifest_path)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("hash mismatch" in error for error in result["errors"]))


class TestReleaseScriptSafety(unittest.TestCase):
    def test_cleanup_is_bounded_and_formal_evidence_is_protected(self):
        text = (Path(__file__).parents[1] / "scripts" / "clean_disposable_runs.ps1").read_text(encoding="utf-8")
        self.assertIn("artifacts\\release-validation", text)
        self.assertIn("output-agentteams-at00[23]", text)
        self.assertIn("SupportsShouldProcess", text)

    def test_release_requires_clean_git_and_verifies_checksums(self):
        text = (Path(__file__).parents[1] / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn("git status --porcelain", text)
        self.assertIn("verify_evidence.py", text)
        self.assertIn("checksums.sha256", text)


if __name__ == "__main__":
    unittest.main()
