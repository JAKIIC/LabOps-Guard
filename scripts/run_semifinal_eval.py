#!/usr/bin/env python3
"""Run Trust Evaluation Suite v1 and write deterministic artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labops.evaluation import run_trust_evaluation_suite  # noqa: E402


def render_markdown(report: dict) -> str:
    metrics = report["metrics"]
    labels = {
        "policy_violation_prevention_rate": "Policy Violation Prevention Rate",
        "evidence_completeness_rate": "Evidence Completeness Rate",
        "false_resolution_rate": "False Resolution Rate",
        "independent_audit_accuracy": "Independent Audit Accuracy",
    }
    lines = [
        "# Trust Evaluation Suite v1.0",
        "",
        "## Scope",
        "",
        report["scope"],
        "",
        "The execution pass reads only `evaluation/cases/inputs/`. The scoring pass reads sealed "
        "expectations from `evaluation/cases/oracles/`. The suite evaluates governance rules, not "
        "general Agent reasoning or broad MLOps coverage.",
        "",
        "## Results",
        "",
        "| Metric | Result | Target | Status |",
        "|---|---:|---:|---|",
    ]
    for key, label in labels.items():
        metric = metrics[key]
        value = f"{metric['value'] * 100:.1f}%"
        target = f"{'≤' if key == 'false_resolution_rate' else '≥'} {metric['target'] * 100:.1f}%"
        lines.append(f"| {label} | {value} | {target} | {'PASS' if metric['passed'] else 'FAIL'} |")
    lines.extend(
        [
            "",
            f"Suite status: **{report['status']}** ({report['case_count']} cases).",
            "",
            "## Case decisions",
            "",
            "| Case | Focus | Decision | Terminal state | Oracle |",
            "|---|---|---|---|---|",
        ]
    )
    for item in report["results"]:
        lines.append(
            f"| `{item['case_id']}` | {item['focus']} | {item['decision']} | "
            f"{item['terminal_state']} | {'MATCH' if item['oracle_match'] else 'MISMATCH'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "These results show that the fixed governance controls block protected-resource changes, "
            "withhold resolution when evidence or approval is incomplete, and require an independent "
            "Verification Auditor. They do not measure model quality, open-ended diagnosis, GPU scale, "
            "or production multi-tenant scheduling.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", type=Path, default=ROOT / "evaluation" / "cases" / "inputs"
    )
    parser.add_argument(
        "--oracles", type=Path, default=ROOT / "evaluation" / "cases" / "oracles"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "results" / "trust-evaluation-suite-v1.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "docs" / "trust-evaluation-report-v1.0.md",
    )
    args = parser.parse_args(argv)
    report = run_trust_evaluation_suite(args.inputs, args.oracles, ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.report.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "cases": report["case_count"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
