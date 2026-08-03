"""Run the checkpoint regression baseline three times and verify stability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import evaluate_run
from train_demo import generate_checkpoints


def run_stability_demo(output: str | Path, repeats: int = 3) -> dict:
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    for index in range(1, repeats + 1):
        run_dir = output / f"run-{index:02d}"
        training = generate_checkpoints(run_dir)
        configured = evaluate_run(run_dir)
        best = evaluate_run(run_dir, "checkpoints/best.pt")
        record = {
            "run_id": f"DEMO-BASELINE-{index:02d}",
            "best_accuracy": best["accuracy"],
            "configured_accuracy": configured["accuracy"],
            "configured_checkpoint": configured["checkpoint"],
            "best_state_sha256": training["best_state_sha256"],
            "last_state_sha256": training["last_state_sha256"],
            "metric_file_sha256": configured["metric_file_sha256"],
        }
        (run_dir / "baseline_metrics.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        runs.append(record)

    best_values = [r["best_accuracy"] for r in runs]
    configured_values = [r["configured_accuracy"] for r in runs]
    report = {
        "schema_version": "1.0",
        "incident_id": "DEMO-RCA-001",
        "repeats": repeats,
        "offline": True,
        "device": "cpu",
        "configured_checkpoint": "checkpoints/last.pt",
        "best_accuracy": best_values[0],
        "current_accuracy": configured_values[0],
        "target_accuracy": 0.88,
        "best_spread": max(best_values) - min(best_values),
        "current_spread": max(configured_values) - min(configured_values),
        "stable": len(set(best_values)) == 1 and len(set(configured_values)) == 1,
        "acceptance": {
            "best_at_least_0_88": min(best_values) >= 0.88,
            "last_between_0_65_and_0_75": all(0.65 <= value <= 0.75 for value in configured_values),
            "regression_at_least_0_15": all(best - current >= 0.15 for best, current in zip(best_values, configured_values)),
            "three_identical_runs": repeats >= 3 and len(set(best_values)) == 1 and len(set(configured_values)) == 1,
        },
        "runs": runs,
    }
    report["passed"] = all(report["acceptance"].values())
    (output / "stability_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/DEMO-RCA-001/baseline")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    report = run_stability_demo(args.output, args.repeats)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

