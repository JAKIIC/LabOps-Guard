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
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages-public-demo.yml"


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
            "Trustworthy Agent Execution &amp; Governance Infrastructure for AI Engineering",
            "Trust Contract v1",
            "Trust State Machine v1",
            "Identity",
            "Policy",
            "Execution",
            "Evidence",
            "Audit",
            "Archived Verified Run",
            "Evidence Replay",
            "Read-only · Static",
            "LABOPS-AT-004-EVAL-DRIFT",
            "71.88% × 3",
            "97.81% × 3",
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
            "评测预处理漂移：已隔离定位并可信修复",
            "Separation of duties",
            "独占终态裁决",
            "7 versioned Skills",
            "Structured I/O Schema",
            "27 ZIP entries",
            "合法分支",
            "危险分支",
            "只允许执行获批计划",
            "终态不得标记为 RESOLVED",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.document)
        self.assertNotIn("71.875%", self.document)
        self.assertNotIn("97.8124976%", self.document)
        self.assertNotIn("27 bundle artifacts", self.document)
        self.assertNotIn("Trust Score", self.document)
        self.assertNotIn("state_machine_v3", self.document)

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
        self.assertIn("from labops.trust import build_trust_snapshot", source)

    def test_pages_artifact_is_limited_to_the_public_demo(self) -> None:
        workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("python -B scripts/build_public_demo.py --check", workflow)
        self.assertIn("path: docs/public-demo", workflow)
        self.assertNotIn("path: docs\n", workflow)
        self.assertNotIn("path: .\n", workflow)


if __name__ == "__main__":
    unittest.main()
