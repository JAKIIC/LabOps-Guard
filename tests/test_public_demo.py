from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "public-demo" / "index.html"
BUILDER = ROOT / "scripts" / "build_public_demo.py"


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class PublicDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = PAGE.read_text(encoding="utf-8")

    def test_page_is_current_and_build_is_read_only(self) -> None:
        evidence_roots = [
            ROOT / "demo" / "output-agentteams-at002",
            ROOT / "demo" / "output-agentteams-at003",
            ROOT / "demo" / "output-agentteams-at004",
        ]
        before = [_tree_digest(path) for path in evidence_roots]
        result = subprocess.run(
            [sys.executable, "-B", str(BUILDER), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, [_tree_digest(path) for path in evidence_roots])

    def test_required_replay_content(self) -> None:
        required = [
            "Archived Verified Run",
            "Evidence Replay",
            "Read-only · Static",
            "LABOPS-AT-004-EVAL-DRIFT",
            "71.875% × 71.875% × 71.875%",
            "97.8124976% × 97.8124976% × 97.8124976%",
            "PASS / RESOLVED",
            "Incident Summary",
            "Evidence 排除过程",
            "Experiment Plan",
            "Human Approval",
            "Runner Execution Result",
            "Before / After Metrics",
            "Trace",
            "Auditor Decision",
            "Evidence Bundle SHA-256",
            "4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd",
            "AT-002 · BLOCKED",
            "POLICY_VIOLATION / ROLLED_BACK",
            "metric.py 非法篡改被拦截",
            "不是实时运行界面",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.document)

    def test_six_agent_order(self) -> None:
        roles = [
            "Incident Commander",
            "Evidence Collector",
            "RCA Analyst",
            "Experiment Planner",
            "Safe Executor",
            "Verification Auditor",
        ]
        offsets = [self.document.index(role) for role in roles]
        self.assertEqual(offsets, sorted(offsets))

    def test_page_has_no_active_or_private_surface(self) -> None:
        forbidden = [
            r"<script\b",
            r"fetch\s*\(",
            r"XMLHttpRequest",
            r"WebSocket",
            r"EventSource",
            r"<form\b",
            r"<input\b",
            r"/api/",
            r"[A-Za-z]:\\",
            r"/(?:Users|home)/",
            r"file://",
            r"localhost",
            r"127\.0\.0\.1",
            r"0\.0\.0\.0",
            r"matrix-local",
            r"(?:^|[^a-z])minio(?:[^a-z]|$)",
            r"api[_ -]?key",
            r"access[_ -]?token",
            r"client[_ -]?secret",
            r"password",
            r"authorization:\s*bearer",
        ]
        for pattern in forbidden:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.document, re.IGNORECASE))
        self.assertIn("connect-src 'none'", self.document)
        self.assertIn("form-action 'none'", self.document)
        self.assertIn("script-src 'none'", self.document)

    def test_builder_reuses_existing_dashboard_parsers(self) -> None:
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("from labops.web import build_agentteams_v2_state, build_at004_state", source)


if __name__ == "__main__":
    unittest.main()
