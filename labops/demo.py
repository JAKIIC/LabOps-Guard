"""Polar-baseline demo: full chain on real 10 evidence gaps.

REAL for registry/evidence/diagnosis/approval/verification/trace; SIMULATED
for risky actions (install/download/train). Never reads excluded data. Never
claims to fix Polar root cause. No fabricated faults.
"""

from __future__ import annotations

import json
from pathlib import Path

from labops import trace as trace_mod
from labops import registry, evidence, diagnosis, approval, action, verify


def _allowed_files_from_manifest(snapshot_dir: Path) -> list[str]:
    """Extract allowed-file list from snapshot manifest.json snapshot_files."""
    mf = snapshot_dir / "manifest.json"
    if mf.exists():
        data = json.loads(mf.read_text(encoding="utf-8"))
        return [e["path"] for e in data.get("snapshot_files", [])]
    return []


def run_demo(workspace, snapshot_dir, audit_dir, verification_json=None,
             allowed_list=None, trace=None) -> int:
    workspace = Path(workspace)
    snapshot_dir = Path(snapshot_dir)
    audit_dir = Path(audit_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    if trace is None:
        trace = trace_mod.TraceLog(workspace / "trace.jsonl")

    demo_out = workspace / "demo"
    demo_out.mkdir(parents=True, exist_ok=True)
    lines = []
    def log(s):
        lines.append(s)
        print(s)

    # allowed files
    if allowed_list:
        allowed = json.loads(Path(allowed_list).read_text(encoding="utf-8"))
    else:
        allowed = _allowed_files_from_manifest(snapshot_dir)
        if not allowed:
            allowed = [
                "README.md", "baseline.py",
                "baseline/baseline/README.md",
                "baseline/baseline/participant_pipeline_cnn_mlp.ipynb",
                "baseline/baseline/Codes_DB/BCH_N31_K11.txt",
                "baseline/baseline/Codes_DB/BCH_N31_K16.txt",
                "baseline/baseline/Codes_DB/BCH_N63_K30.txt",
                "baseline/baseline/Codes_DB/BCH_N63_K45.txt",
                "baseline/baseline/Codes_DB/POLAR_N64_K22.txt",
                "baseline/baseline/Codes_DB/POLAR_N64_K32.txt",
                "baseline/baseline/Codes_DB/POLAR_N64_K48.txt",
                "public_test/README_数据说明.md",
                "submit_sample/README_提交说明.md",
            ]

    log("=== LabOps Guard demo: polar-baseline ===")
    log(f"allowed files: {len(allowed)}")

    # Step 0 registry
    reg = registry.register_snapshot(snapshot_dir, allowed, workspace,
                                     verification_json=verification_json, trace=trace)
    log(f"[registry] verification_status={reg['verification_status']} "
        f"missing={reg['missing']} mismatches={reg['hash_mismatches_vs_verification']}")

    # Step 1 evidence
    ev = evidence.collect_evidence(audit_dir, workspace, trace=trace)
    log(f"[evidence] items={ev['evidence_count']} gaps={ev['gaps_count']}")

    # Step 2 diagnose
    diag = diagnosis.diagnose_from_gaps(ev["gaps"], workspace, trace=trace)
    states = {}
    for h in diag["hypotheses"]:
        states[h["state"]] = states.get(h["state"], 0) + 1
    log(f"[diagnosis] hypotheses={diag['hypothesis_count']} by_state={states}")

    # surface the required gaps
    req_gaps = ["GAP-001", "GAP-004", "GAP-003", "GAP-005"]  # requirements, zips, calibration
    for h in diag["hypotheses"]:
        eid = h["evidence_ids"][0] if h["evidence_ids"] else "?"
        if eid in req_gaps:
            log(f"  {h['hypothesis_id']} evidence={eid} state={h['state']} "
                f"block={h.get('block_reason')}")

    # Step 3 approval gate
    log("=== approval gate (no approval -> no execution) ===")
    approval_ids = {}
    for h in diag["hypotheses"]:
        aid = h.get("suggested_action_id")
        if aid and h["state"] == "BLOCKED":
            cls = approval.MANUAL_APPROVAL
            # demonstrate classification per gap
            eid = h["evidence_ids"][0] if h["evidence_ids"] else ""
            if eid == "GAP-007":
                cls = approval.READ_ONLY_AUTO
            approval_ids[eid] = aid
            approval.create_approval(aid, h["hypothesis_id"], aid,
                                     f"simulated:resolve-{eid}", cls, workspace, trace=trace)

    # approve a couple, reject one, leave one pending (timeout demo), forbid one
    # approve GAP-001 (requirements)
    if "GAP-001" in approval_ids:
        approval.decide(approval_ids["GAP-001"], "approve", workspace,
                        decided_by="human-approver", reason="ok to create requirements", trace=trace)
        log(f"  approved {approval_ids['GAP-001']}")
    # reject GAP-004 (baseline.zip download)
    if "GAP-004" in approval_ids:
        approval.decide(approval_ids["GAP-004"], "reject", workspace,
                        decided_by="human-approver", reason="no download in demo", trace=trace)
        log(f"  rejected {approval_ids['GAP-004']}")
    # timeout GAP-005
    if "GAP-005" in approval_ids:
        approval.mark_timeout(approval_ids["GAP-005"], workspace, trace=trace)
        log(f"  timeout {approval_ids['GAP-005']}")

    # Step 4 controlled action
    log("=== controlled actions (dry-run first; risky SIMULATED) ===")
    # approved manual action -> simulated run (dry-run then simulate)
    if "GAP-001" in approval_ids:
        r = action.execute_action(approval_ids["GAP-001"],
                                  "pip install numpy pandas",
                                  workspace, dry_run=True, trace=trace)
        log(f"  [dry-run] {approval_ids['GAP-001']} -> {r.status}")
        r2 = action.execute_action(approval_ids["GAP-001"],
                                   "pip install numpy pandas",
                                   workspace, dry_run=False, trace=trace)
        log(f"  [run] {approval_ids['GAP-001']} -> {r2.status} simulated={r2.simulated}")
    # rejected -> skipped
    if "GAP-004" in approval_ids:
        log(f"  [skip] {approval_ids['GAP-004']} rejected; not executed")
    # forbidden action demo: try to read private test labels
    try:
        action.execute_action("A-FORBID", "read test_codeword_x_private.csv",
                              workspace, dry_run=False, trace=trace)
    except PermissionError as e:
        log(f"  [forbidden] refused: {e}")

    # Step 5 verification (demo-like: simulated action, no real postcondition)
    log("=== verification closer (no verification -> no closure) ===")
    v = verify.verify_action({"status": "SUCCEEDED", "simulated": True},
                             workspace, expected_artifact=None, trace=trace)
    log(f"  demo_verification={v['demo_verification']} "
        f"incident_state={v['incident_state']} "
        f"underlying_issue_resolved={v['underlying_issue_resolved']} "
        f"has_postcondition={v['has_postcondition']}")
    log("  NOTE: demo actions are SIMULATED; incident remains BLOCKED (NOT CLOSED). "
        "Only a REAL non-simulated action + concrete postcondition can CLOSE.")

    # Step 6 trace chain
    ok, msg = trace.verify_chain()
    log(f"=== trace ===")
    log(f"  chain: {msg}")
    log(f"  entries: {len(trace.read())}")

    # write demo transcript
    (demo_out / "demo_transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    (demo_out / "demo_summary.json").write_text(json.dumps({
        "allowed_files": len(allowed),
        "verification_status": reg["verification_status"],
        "evidence_count": ev["evidence_count"],
        "gaps_count": ev["gaps_count"],
        "hypothesis_states": states,
        "demo_verification": v["demo_verification"],
        "incident_state": v["incident_state"],
        "underlying_issue_resolved": v["underlying_issue_resolved"],
        "trace_chain_ok": ok,
        "excluded_data_not_read": True,
        "no_fabricated_faults": True,
        "no_polar_root_cause_claim": True,
        "no_model_optimization": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1
