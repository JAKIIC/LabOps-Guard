"""Deterministic standard-library stub for the LabOps Guard compatibility fixture."""

from __future__ import annotations

import json
from pathlib import Path


def load_expected_accuracy(root: Path) -> float:
    payload = json.loads((root / "artifacts" / "expected_metrics.json").read_text(encoding="utf-8"))
    return float(payload["accuracy"])


if __name__ == "__main__":
    print(f"accuracy={load_expected_accuracy(Path(__file__).parent):.2f}")
