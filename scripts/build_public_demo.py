#!/usr/bin/env python3
"""Build the public, static LabOps Guard evidence replay.

The builder reuses the Dashboard's evidence parsers, validates the archived
AT-004 and AT-002 records, and emits only an explicit public allowlist.  It is
intentionally a build-time tool: the generated page has no API calls or active
controls.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labops.web import build_agentteams_v2_state, build_at004_state  # noqa: E402


TEMPLATE = ROOT / "labops" / "public_demo.html"
DEFAULT_OUTPUT = ROOT / "docs" / "public-demo" / "index.html"
AT004_ROOT = ROOT / "demo" / "output-agentteams-at004"
AT002_ROOT = ROOT / "demo" / "output-agentteams-at002"

AT004_BUNDLE_SHA256 = "4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd"
ROLE_ORDER = [
    "Incident Commander",
    "Evidence Collector",
    "RCA Analyst",
    "Experiment Planner",
    "Safe Executor",
    "Verification Auditor",
]


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Public demo source rejected: {message}")


def _validate_sources(at004: dict[str, Any], at002: dict[str, Any]) -> None:
    """Fail closed if the archived cases no longer match the verified record."""

    _expect(at004.get("ready") is True, "AT-004 is not ready")
    _expect(at004.get("source_mode") == "AGENTTEAMS_RUN", "AT-004 is not an AgentTeams run")
    _expect(at004.get("task_id") == "LABOPS-AT-004-EVAL-DRIFT", "unexpected AT-004 task")
    _expect(at004.get("status") == "PASS", "AT-004 decision is not PASS")
    _expect(at004.get("resolution_status") == "RESOLVED", "AT-004 is not RESOLVED")
    _expect(at004.get("agentteams", {}).get("six_roles_run") is True, "six Agent roles did not run")
    _expect(
        [item.get("role") for item in at004.get("agentteams", {}).get("roles", [])] == ROLE_ORDER,
        "six-role order changed",
    )

    runs = at004.get("runs", [])
    _expect(len(runs) == 1, "AT-004 must contain exactly one archived run")
    run = runs[0]
    _expect(run.get("baseline_values") == [0.71875] * 3, "baseline values changed")
    _expect(run.get("candidate_values") == [0.9781249761581421] * 3, "candidate values changed")
    _expect(run.get("decision") == "PASS", "Runner decision is not PASS")
    _expect(run.get("network") == "none", "Runner network was not disabled")
    _expect(run.get("sandbox_only") is True, "Runner was not sandbox-only")
    _expect(run.get("approval_before_execution") is True, "execution preceded approval")
    _expect(run.get("protected_hashes_ok") is True, "protected hashes did not verify")
    _expect(run.get("artifact_hashes_ok") is True, "Runner artifact hashes did not verify")

    plan = at004.get("plan", {})
    changes = plan.get("changes", [])
    _expect(len(changes) == 1, "plan is not single-variable")
    _expect(
        changes[0]
        == {
            "file": "eval_config.json",
            "field": "evaluation.preprocessing_profile",
            "before": "train_augmented",
            "after": "eval_standard",
        },
        "plan change is outside the verified allowlist",
    )
    _expect(all(at004.get("plan_checks", {}).values()), "one or more plan checks failed")
    _expect(at004.get("approval", {}).get("decision") == "APPROVED", "human approval missing")
    _expect(at004.get("approval", {}).get("before_execution") is True, "approval order invalid")
    _expect(at004.get("capability", {}).get("all_pass") is True, "capability check failed")
    _expect(all(at004.get("capability", {}).get("checks", {}).values()), "capability item failed")
    _expect(all(at004.get("integrity", {}).values()), "AT-004 integrity check failed")
    _expect(at004.get("trace", {}).get("ok") is True, "trace chain failed")
    _expect(at004.get("trace", {}).get("entries") == 7, "unexpected trace length")
    _expect(at004.get("trace", {}).get("final_audit") == "CHAIN_OK", "trace audit failed")
    _expect(at004.get("trace", {}).get("final_acceptance") == "ACCEPTED", "trace not accepted")
    _expect(at004.get("bundle", {}).get("sha256") == AT004_BUNDLE_SHA256, "bundle digest changed")
    _expect(at004.get("bundle", {}).get("artifact_count") == 27, "bundle member count changed")

    _expect(at002.get("ready") is True, "AT-002 is not ready")
    _expect(at002.get("final_state") == "BLOCKED", "AT-002 must remain BLOCKED")
    unsafe = at002.get("unsafe_case", {})
    _expect(unsafe.get("decision") == "POLICY_VIOLATION", "unsafe decision changed")
    _expect(unsafe.get("resolution_status") == "ROLLED_BACK", "unsafe case was not rolled back")
    _expect(unsafe.get("tamper_detected") is True, "metric tamper was not detected")
    _expect(unsafe.get("rollback_ok") is True, "unsafe rollback failed")
    _expect(unsafe.get("hash_restored") is True, "metric hash was not restored")
    _expect(unsafe.get("restored_hash") == unsafe.get("original_hash"), "restored hash mismatch")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float, decimals: int) -> str:
    return f"{value * 100:.{decimals}f}%"


def _rows(items: Iterable[tuple[str, object]]) -> str:
    return "".join(
        f'<div class="row"><span>{_e(label)}</span><b>{_e(value)}</b></div>'
        for label, value in items
    )


def _render_agents(roles: list[dict[str, Any]]) -> str:
    return "".join(
        f'<div class="agent"><div class="agent-num">{index:02d}</div>'
        f'<b>{_e(role["role"])}</b><span>{_e(role["status"])}</span></div>'
        for index, role in enumerate(roles, 1)
    )


def _render_trace(handoffs: list[dict[str, Any]]) -> str:
    public_trace = []
    for item in handoffs:
        public_trace.append(
            {
                "sequence": item["handoff"],
                "route": f'{item["from"]} → {item["to"]}',
                "event": item["event"].replace("_", " "),
                "time": item["source_event_time"],
                "status": item["status"],
            }
        )
    return "".join(
        '<div class="trace-item">'
        f'<div class="seq">{_e(item["sequence"])}</div>'
        f'<div><b>{_e(item["route"])}</b>'
        f'<p>{_e(item["event"])} · {_e(item["time"])}</p></div>'
        f'<div class="trace-status">{_e(item["status"])}</div></div>'
        for item in public_trace
    )


def _render_content(at004: dict[str, Any], at002: dict[str, Any]) -> str:
    run = at004["runs"][0]
    plan = at004["plan"]
    change = plan["changes"][0]
    budget = plan["budget"]
    approval = at004["approval"]
    capability = at004["capability"]
    trace = at004["trace"]
    bundle = at004["bundle"]
    unsafe = at002["unsafe_case"]

    baseline = f'{_pct(run["baseline_accuracy"], 2)} × {len(run["baseline_values"])}'
    candidate = f'{_pct(run["candidate_accuracy"], 2)} × {len(run["candidate_values"])}'
    checks = "".join(
        f'<div class="check">{_e(name.replace("_", " "))}</div>'
        for name, passed in capability["checks"].items()
        if passed
    )

    exclusions = [
        ("Checkpoint", "EXCLUDED", "Current hash equals the archived reference hash."),
        ("Validation data", "EXCLUDED", "Dataset hash equals the archived reference hash."),
        ("metric.py", "EXCLUDED", "Metric implementation hash is unchanged."),
        ("Random variance", "EXCLUDED", "Three baseline repeats have zero spread."),
        ("Preprocessing drift", "CONFIRMED", "The controlled one-variable experiment restored the target metric."),
    ]
    exclusions_html = "".join(
        f'<div class="card {"confirmed" if state == "CONFIRMED" else "excluded"}">'
        f'<div class="state">{_e(state)}</div><h3>{_e(title)}</h3><p>{_e(reason)}</p></div>'
        for title, state, reason in exclusions
    )

    forbidden = ", ".join(plan["forbidden_changes"])
    at002_reason = (
        "The approved checkpoint experiment stayed blocked because the Worker evaluation environment "
        "did not provide torch; no passing postcondition was claimed."
    )

    return f"""
    <section class="panel hero">
      <div class="kicker">AT-004 · archived verified run</div>
      <h1>评测预处理漂移：已隔离定位并可信修复</h1>
      <p>六个 Agent 基于归档证据完成诊断、受控实验与独立复核。这里展示的是经过完整性校验的 Evidence Replay，不是实时运行界面。</p>
      <div class="truth-line"><span>PASS / RESOLVED</span><span>6 Agent roles ran</span><span>Human approval before execution</span><span>Trace CHAIN_OK</span></div>
    </section>

    <section class="section" aria-labelledby="incident-summary">
      <div class="head"><h2 id="incident-summary">Incident Summary</h2><p>PUBLIC ALLOWLIST VIEW</p></div>
      <div class="summary">
        <div class="panel summary-card"><div class="label">Archived task</div><div class="value">{_e(at004["task_id"])}</div><div class="tiny">Evaluation preprocessing drift</div></div>
        <div class="panel summary-card"><div class="label">Decision</div><div class="value ok">{_e(at004["status"])}</div><div class="tiny">Independent verification</div></div>
        <div class="panel summary-card"><div class="label">Resolution</div><div class="value ok">{_e(at004["resolution_status"])}</div><div class="tiny">Target ≥ 97.00%</div></div>
        <div class="panel summary-card"><div class="label">Evidence</div><div class="value">{_e(at004["evidence_count"])} facts</div><div class="tiny">27 ZIP entries</div></div>
      </div>
    </section>

    <section class="section" aria-labelledby="metrics">
      <div class="head"><h2 id="metrics">Before / After Metrics</h2><p>THREE REPEATS · ZERO SPREAD</p></div>
      <div class="metric-stage">
        <div class="panel score before"><div class="label">Before · train_augmented</div><div class="number">{_pct(run["baseline_accuracy"], 2)}</div><div class="repeat">{_e(baseline)}</div></div>
        <div class="arrow" aria-hidden="true">→</div>
        <div class="panel score after"><div class="label">After · eval_standard</div><div class="number">{_pct(run["candidate_accuracy"], 2)}</div><div class="repeat">{_e(candidate)}</div></div>
      </div>
    </section>

    <section class="section" aria-labelledby="agents">
      <div class="head"><h2 id="agents">六 Agent 协作顺序</h2><p>HUMAN APPROVAL IS A SEPARATE GATE</p></div>
      <div class="panel agents">{_render_agents(at004["agentteams"]["roles"])}</div>
      <div class="panel duty-grid" aria-label="Separation of duties">
        <div class="duty"><b>Commander</b><span>编排与封包，不能覆盖终态裁决</span></div>
        <div class="duty"><b>Collector</b><span>只能取证，不能诊断</span></div>
        <div class="duty"><b>Analyst</b><span>只能诊断，不能执行</span></div>
        <div class="duty"><b>Planner</b><span>只能制定计划，不能审批</span></div>
        <div class="duty"><b>Executor</b><span>只能执行获批计划，不能宣布成功</span></div>
        <div class="duty"><b>Auditor</b><span>独占终态裁决，不能修改结果</span></div>
      </div>
    </section>

    <section class="section" aria-labelledby="evidence">
      <div class="head"><h2 id="evidence">Evidence 排除过程</h2><p>HASHES FIRST · CAUSATION BY CONTROLLED EXPERIMENT</p></div>
      <div class="cards">{exclusions_html}</div>
    </section>

    <section class="section grid2" aria-label="Experiment and approval">
      <div class="panel pad">
        <div class="kicker">Experiment Plan</div><h2>只改变一个评估配置</h2>
        <div class="change"><div class="label">{_e(change["file"])} · {_e(change["field"])}</div><div class="change-code"><span class="from">{_e(change["before"])}</span> → <span class="to">{_e(change["after"])}</span></div></div>
        <div class="list">{_rows([
            ("Budget", f'{budget["device"].upper()} · no network · ≤ {budget["max_runtime_seconds"]}s · {budget["repeats"]} repeats'),
            ("Approval gate", "Explicit and required"),
            ("Rollback", "Restore the original profile or discard the sandbox"),
            ("Forbidden", forbidden),
        ])}</div>
      </div>
      <div class="panel pad approval">
        <div class="kicker">Human Approval</div><div class="seal">APPROVED</div>
        <p>人工审批是独立安全门，不计入六个 Agent 角色。</p>
        <div class="list">{_rows([
            ("Approval ID", approval["approval_id"]),
            ("Approved at", approval["approved_at"]),
            ("Before execution", "YES" if approval["before_execution"] else "NO"),
            ("Scope", "Only the allowlisted one-variable sandbox experiment"),
        ])}</div>
      </div>
    </section>

    <section class="section grid2" aria-label="Runner and capability checks">
      <div class="panel pad runner">
        <div class="kicker">Runner Execution Result</div><div class="seal">PASS</div>
        <div class="list">{_rows([
            ("Archived image", at004["runner_image"]),
            ("Command", plan["command"]),
            ("Isolation", "CPU-only · no network · sandbox-only"),
            ("Runtime", f'Python {capability["runtime"]["python"]} · torch {capability["runtime"]["torch"]}'),
            ("Protected hashes", "VERIFIED"),
            ("Artifact hashes", "VERIFIED"),
        ])}</div>
      </div>
      <div class="panel pad">
        <div class="kicker">Runtime Capability Check</div><h2>All preflight controls passed</h2>
        <div class="checklist">{checks}</div>
      </div>
    </section>

    <section class="section" aria-labelledby="trace">
      <div class="head"><h2 id="trace">Trace</h2><p>{_e(trace["message"].upper())} · FINAL {_e(trace["final_audit"])} / {_e(trace["final_acceptance"])}</p></div>
      <div class="panel trace">{_render_trace(at004["agentteams"]["handoffs"])}</div>
    </section>

    <section class="section" aria-labelledby="reusable-infra">
      <div class="head"><h2 id="reusable-infra">Reusable Infra</h2><p>NOT A ONE-OFF SCRIPT</p></div>
      <div class="panel infra"><div><div class="kicker">可复用能力合同</div><h3>7 versioned Skills</h3><p>同一组职责边界可迁移到训练、评测、数据处理和发布验证。</p></div><div class="infra-items"><span>Structured I/O Schema</span><span>Sandbox execution contract</span><span>Policy + approval gate</span><span>Case Memory</span></div></div>
    </section>

    <section class="section" aria-labelledby="auditor">
      <div class="head"><h2 id="auditor">Auditor Decision</h2><p>INDEPENDENT RECOMPUTATION</p></div>
      <div class="panel decision"><div><div class="kicker">Verification Auditor</div><h3>PASS / RESOLVED</h3><p>三次候选结果达到冻结阈值；重复性、审批顺序、受保护输入、Runner 产物和 Trace 哈希链均通过独立复核。</p></div><div class="decision-mark">VERIFIED</div></div>
    </section>

    <section class="section" aria-labelledby="bundle">
      <div class="head"><h2 id="bundle">Evidence Bundle SHA-256</h2><p>{_e(bundle["artifact_count"])} ZIP ENTRIES · MEMBER SET VERIFIED</p></div>
      <div class="panel bundle"><div><div class="label">AT-004 archived evidence bundle · 27 ZIP entries</div><div class="digest">{_e(bundle["sha256"])}</div></div><span class="pill verified">HASH VERIFIED</span></div>
    </section>

    <section class="section branches" aria-labelledby="safety-branches">
      <div class="head"><h2 id="safety-branches">辅助安全分支</h2><p>ARCHIVED CASES · UNCHANGED</p></div>
      <div class="grid2">
        <div class="card blocked"><div class="state">AT-002 · BLOCKED</div><h3>缺少运行依赖时安全阻塞</h3><p>{_e(at002_reason)}</p><div class="list">{_rows([("Valid case", "INCONCLUSIVE"), ("Resolution", "DEMO_PASSED_NOT_RESOLVED")])}</div></div>
        <div class="card rolled"><div class="state">POLICY_VIOLATION / ROLLED_BACK</div><h3>metric.py 非法篡改被拦截</h3><p>策略检测到受保护评测逻辑发生变化，执行被阻断并回滚；恢复后的哈希与冻结原始值一致。</p><div class="list">{_rows([("Tamper detected", "YES"), ("Rollback", "VERIFIED"), ("Hash restored", "YES" if unsafe["hash_restored"] else "NO")])}</div></div>
      </div>
    </section>
    """


_FORBIDDEN_OUTPUT_PATTERNS = {
    "Windows absolute path": re.compile(r"[A-Za-z]:\\"),
    "Unix home path": re.compile(r"/(?:Users|home)/", re.IGNORECASE),
    "local file URL": re.compile(r"file://", re.IGNORECASE),
    "loopback host": re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0)", re.IGNORECASE),
    "private control-plane hostname": re.compile(r"matrix-local|(?:^|[^a-z])minio(?:[^a-z]|$)", re.IGNORECASE),
    "credential-like field": re.compile(
        r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password|authorization:\s*bearer)",
        re.IGNORECASE,
    ),
    "live API call": re.compile(r"fetch\s*\(|XMLHttpRequest|WebSocket|EventSource|/api/", re.IGNORECASE),
    "active form": re.compile(r"<form\b|<input\b", re.IGNORECASE),
}


def _validate_public_html(document: str) -> None:
    for label, pattern in _FORBIDDEN_OUTPUT_PATTERNS.items():
        _expect(pattern.search(document) is None, f"generated HTML contains {label}")
    _expect("{{PUBLIC_DEMO_CONTENT}}" not in document, "template placeholder remains")
    _expect("<script" not in document.lower(), "generated HTML contains script")
    _expect("connect-src 'none'" in document, "CSP does not disable network connections")
    _expect("form-action 'none'" in document, "CSP does not disable form submission")


def build() -> str:
    at004 = build_at004_state(AT004_ROOT)
    at002 = build_agentteams_v2_state(AT002_ROOT)
    _validate_sources(at004, at002)
    template = TEMPLATE.read_text(encoding="utf-8")
    _expect(template.count("{{PUBLIC_DEMO_CONTENT}}") == 1, "template placeholder is invalid")
    document = template.replace("{{PUBLIC_DEMO_CONTENT}}", _render_content(at004, at002))
    document = "\n".join(line.rstrip() for line in document.splitlines()) + "\n"
    _validate_public_html(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the committed static page exactly matches the archived evidence",
    )
    args = parser.parse_args()
    document = build()
    output = args.output.resolve()
    if args.check:
        _expect(output.exists(), f"generated page is missing: {output}")
        _expect(output.read_text(encoding="utf-8") == document, "generated page is stale")
        print(f"Public demo verified: {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8", newline="\n")
    print(f"Public demo written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
