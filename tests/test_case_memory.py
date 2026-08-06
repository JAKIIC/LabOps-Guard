"""Case-memory search and deterministic closure-pack tests."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from labops.case_memory import build_closure_bundle, load_cases, search_cases


class TestCaseMemory(unittest.TestCase):
    def test_at004_is_searchable_without_external_services(self):
        cases = load_cases()
        self.assertTrue(any(case["incident_id"] == "DEMO-EVAL-DRIFT-004" for case in cases))
        results = search_cases("evaluation drift")
        self.assertEqual(results[0]["incident_id"], "DEMO-EVAL-DRIFT-004")
        self.assertEqual(results[0]["final_state"], "RESOLVED")

    def test_invalid_case_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.json").write_text(json.dumps({"schema_version": "9"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(tmp)

    def test_closure_bundle_is_deterministic_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source")
            source.mkdir()
            for name, content in {
                "postmortem.json": "{}\n",
                "case_memory.json": "{}\n",
                "postmortem.md": "# Postmortem\n",
                "secret.txt": "must not ship",
            }.items():
                Path(source, name).write_text(content, encoding="utf-8")
            first = build_closure_bundle(source, Path(tmp, "one.zip"))
            second = build_closure_bundle(source, Path(tmp, "two.zip"))
            self.assertEqual(first["sha256"], second["sha256"])
            with zipfile.ZipFile(Path(tmp, "one.zip")) as archive:
                self.assertEqual(set(archive.namelist()), {
                    "postmortem.json", "case_memory.json", "postmortem.md", "closure_manifest.json"
                })


if __name__ == "__main__":
    unittest.main()
