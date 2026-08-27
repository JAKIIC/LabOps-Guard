#!/usr/bin/env python3
"""LabOps Guard CLI - local-first controlled experiment operations.

Standard-library only. Subcommands:
  init      register snapshot (hashes + verification)
  evidence  collect evidence
  diagnose  build hypotheses (evidence_id required)
  approve   list / review / timeout approvals
  run       execute a controlled action (dry-run first)
  verify    verify post-action closure
  trace     dump / verify trace chain
  skills    list, describe, or validate a registered Skill
  trust     emit the evidence-backed Trust Layer snapshot
  demo      run the polar-baseline demo end-to-end
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from labops import trace as trace_mod
from labops import registry, evidence, diagnosis, approval, action, verify


def _ws(args) -> Path:
    return Path(args.workspace)


def _trace(args):
    return trace_mod.TraceLog(_ws(args) / "trace.jsonl")


def cmd_init(args) -> int:
    allowed = args.allowed_files or []
    # if provided as a JSON list file
    if args.allowed_list:
        allowed = json.loads(Path(args.allowed_list).read_text(encoding="utf-8"))
    record = registry.register_snapshot(
        snapshot_dir=args.snapshot,
        allowed_files=allowed,
        workspace=_ws(args),
        verification_json=args.verification,
        trace=_trace(args),
        project_ref=args.project,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_evidence(args) -> int:
    rec = evidence.collect_evidence(args.audit_dir, _ws(args), trace=_trace(args))
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def cmd_diagnose(args) -> int:
    # load collected evidence gaps
    ce = _ws(args) / "collected_evidence.json"
    if not ce.exists():
        print("no collected_evidence.json; run 'evidence' first", file=sys.stderr)
        return 1
    gaps = json.loads(ce.read_text(encoding="utf-8")).get("gaps", [])
    rec = diagnosis.diagnose_from_gaps(gaps, _ws(args), trace=_trace(args))
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def cmd_approve(args) -> int:
    if args.action == "request":
        required = {
            "approval_id": args.approval_id,
            "hypothesis_id": args.hypothesis_id,
            "action_id": args.action_id,
            "command": args.command,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            print(f"approval request missing: {', '.join(missing)}", file=sys.stderr)
            return 1
        try:
            cls = approval.classify_action(args.action_id, args.command, args.action_class)
        except approval.PolicyDowngradeError as exc:
            print(f"POLICY_DOWNGRADE_REFUSED: {exc}", file=sys.stderr)
            return 2
        if cls == approval.FORBIDDEN:
            print("FORBIDDEN: forbidden actions cannot be approved", file=sys.stderr)
            return 2
        if cls != approval.MANUAL_APPROVAL:
            print("read-only action does not require a manual approval request", file=sys.stderr)
            return 1
        req = approval.create_approval(
            args.approval_id,
            args.hypothesis_id,
            args.action_id,
            args.command,
            cls,
            _ws(args),
            trace=_trace(args),
        )
        print(json.dumps(req, ensure_ascii=False, indent=2))
        return 0
    if args.action == "list":
        reqs = approval.load_approvals(_ws(args))
        print(json.dumps(reqs, ensure_ascii=False, indent=2))
        return 0
    if args.action == "review":
        d = approval.decide(args.approval_id, args.decision, _ws(args),
                            decided_by=args.decided_by, reason=args.reason,
                            trace=_trace(args))
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    if args.action == "timeout":
        d = approval.mark_timeout(args.approval_id, _ws(args), trace=_trace(args))
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    print("unknown approve action", file=sys.stderr)
    return 1


def cmd_run(args) -> int:
    # require approval for manual/forbidden classes
    try:
        cls = approval.classify_action(args.action_id, args.command, args.action_class)
    except approval.PolicyDowngradeError as e:
        print(f"POLICY_DOWNGRADE_REFUSED: {e}", file=sys.stderr)
        return 2
    if cls == approval.FORBIDDEN:
        try:
            action.execute_action(args.action_id, args.command, _ws(args),
                                  workdir=args.workdir, dry_run=args.dry_run,
                                  timeout_seconds=args.timeout, trace=_trace(args))
        except PermissionError as e:
            print(f"FORBIDDEN: {e}", file=sys.stderr)
            return 2
        return 2
    if cls == approval.MANUAL_APPROVAL:
        if not args.approval_id:
            print("manual_approval action requires --approval-id (approved first)", file=sys.stderr)
            return 1
        if not approval.is_approved(args.approval_id, _ws(args)):
            print(f"approval {args.approval_id} not approved; refusing to execute", file=sys.stderr)
            return 1
    res = action.execute_action(args.action_id, args.command, _ws(args),
                                workdir=args.workdir, dry_run=args.dry_run,
                                timeout_seconds=args.timeout, trace=_trace(args))
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args) -> int:
    # load last action result
    if args.action_result_json:
        ar = json.loads(Path(args.action_result_json).read_text(encoding="utf-8"))
    else:
        # simulate a verification of a recorded action by reading from a file if given
        ar = {"status": args.status or "SUCCEEDED"}
    res = verify.verify_action(ar, _ws(args),
                               expected_artifact=args.expected_artifact,
                               expected_hash=args.expected_hash,
                               trace=_trace(args))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_trace(args) -> int:
    t = _trace(args)
    if args.verify:
        ok, msg = t.verify_chain()
        print(f"{'OK' if ok else 'FAIL'}: {msg}")
        return 0 if ok else 1
    recs = t.read()
    print(json.dumps(recs, ensure_ascii=False, indent=2))
    return 0


def cmd_demo(args) -> int:
    from labops import demo as demo_mod
    return demo_mod.run_demo(workspace=_ws(args), snapshot_dir=args.snapshot,
                             audit_dir=args.audit_dir,
                             verification_json=args.verification,
                             allowed_list=args.allowed_list,
                             trace=_trace(args))


def cmd_run_incident(args) -> int:
    from labops.checkpoint_incident import run_incident
    result = run_incident(args.incident, args.workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["decision"] in ("PASS", "POLICY_VIOLATION") else 1


def cmd_web(args) -> int:
    from labops import web as web_mod
    project_root = Path(__file__).resolve().parent.parent
    if args.run_demo:
        rc = web_mod.run_bundled_demo(_ws(args), project_root)
        if rc != 0:
            return rc
    web_mod.serve(
        _ws(args),
        host=args.host,
        port=args.port,
        checkpoint_workspace=args.checkpoint_workspace,
        agentteams_v2_workspace=args.agentteams_v2_workspace,
        agentteams_v3_workspace=args.agentteams_v3_workspace,
        at004_workspace=args.at004_workspace,
    )
    return 0


def cmd_skills(args) -> int:
    from labops import skill_registry

    project_root = Path(__file__).resolve().parent.parent
    try:
        if args.action == "list":
            payload = {"schema_version": "1.0", "skills": skill_registry.list_skills(project_root)}
        elif args.action == "describe":
            payload = skill_registry.describe_skill(
                args.skill_id, project_root, caller_agent_id=args.caller_agent_id
            )
        elif args.action == "validate":
            document = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
            payload = skill_registry.validate_skill_input(
                args.skill_id,
                document,
                project_root,
                caller_agent_id=args.caller_agent_id,
            )
        elif args.action == "validate-output":
            document = json.loads(Path(args.output_json).read_text(encoding="utf-8"))
            payload = skill_registry.validate_skill_output(
                args.skill_id,
                document,
                project_root,
                caller_agent_id=args.caller_agent_id,
            )
        else:
            document = json.loads(Path(args.event_json).read_text(encoding="utf-8"))
            payload = skill_registry.validate_skill_usage_event(document, project_root)
    except (OSError, json.JSONDecodeError, ValueError, PermissionError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_trust(args) -> int:
    from labops.trust import build_trust_snapshot

    project_root = Path(__file__).resolve().parent.parent
    at004 = Path(args.at004_root) if args.at004_root else project_root / "demo" / "output-agentteams-at004"
    at002 = Path(args.at002_root) if args.at002_root else project_root / "demo" / "output-agentteams-at002"
    payload = build_trust_snapshot(project_root, at004, at002)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["contract_status"] == "CONFIGURED" else 2


def cmd_demo_readiness(args) -> int:
    from labops.demo_readiness import build_readiness

    project_root = Path(__file__).resolve().parent.parent
    payload = build_readiness(
        project_root,
        service_checks=args.service_checks,
        show_prompt=args.show_prompt,
        gateway_url=args.gateway_url,
        dashboard_url=args.dashboard_url,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "LOCAL_READY" else 2


def cmd_live_demo(args) -> int:
    from labops.live_demo import prepare_session, verify_session

    project_root = Path(__file__).resolve().parent.parent
    sessions_root = (
        Path(args.sessions_root)
        if args.sessions_root
        else project_root / "demo" / "live-sessions"
    )
    try:
        if args.action == "prepare":
            payload = prepare_session(project_root, sessions_root, args.session)
        else:
            payload = verify_session(project_root, sessions_root, args.session)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] in {"PREPARED", "VERIFIED"} else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="labops", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--workspace", required=True, help="LabOps workspace dir")

    sp = sub.add_parser("init", help="register snapshot + hashes")
    add_common(sp)
    sp.add_argument("--snapshot", required=True)
    sp.add_argument("--allowed-files", nargs="*", default=[])
    sp.add_argument("--allowed-list", default=None, help="JSON file with allowed-file list")
    sp.add_argument("--verification", default=None)
    sp.add_argument("--project", default="polar-baseline")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("evidence", help="collect evidence")
    add_common(sp)
    sp.add_argument("--audit-dir", required=True)
    sp.set_defaults(func=cmd_evidence)

    sp = sub.add_parser("diagnose", help="build hypotheses")
    add_common(sp)
    sp.set_defaults(func=cmd_diagnose)

    sp = sub.add_parser("approve", help="approval gate")
    add_common(sp)
    sp.add_argument("action", choices=["request", "list", "review", "timeout"])
    sp.add_argument("--approval-id", default=None)
    sp.add_argument("--hypothesis-id", default=None)
    sp.add_argument("--action-id", default=None)
    sp.add_argument("--command", default=None)
    sp.add_argument("--action-class", choices=["read_only_auto", "manual_approval", "forbidden"], default=None)
    sp.add_argument("--decision", choices=["approve", "reject"], default=None)
    sp.add_argument("--decided-by", default="human-approver")
    sp.add_argument("--reason", default=None)
    sp.set_defaults(func=cmd_approve)

    sp = sub.add_parser("run", help="execute controlled action")
    add_common(sp)
    sp.add_argument("--action-id", required=True)
    sp.add_argument("--command", required=True)
    sp.add_argument("--action-class", choices=["read_only_auto", "manual_approval", "forbidden"], default=None)
    sp.add_argument("--approval-id", default=None)
    sp.add_argument("--workdir", default=None)
    sp.add_argument("--no-dry-run", action="store_true", help="disable dry-run (dangerous)")
    sp.add_argument("--timeout", type=int, default=60)
    sp.set_defaults(func=cmd_run, dry_run=True)

    sp = sub.add_parser("verify", help="verification closer")
    add_common(sp)
    sp.add_argument("--action-result-json", default=None)
    sp.add_argument("--expected-artifact", default=None)
    sp.add_argument("--expected-hash", default=None)
    sp.add_argument("--status", default=None)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("trace", help="dump/verify trace")
    add_common(sp)
    sp.add_argument("--verify", action="store_true")
    sp.set_defaults(func=cmd_trace)

    sp = sub.add_parser("demo", help="run polar-baseline demo")
    add_common(sp)
    sp.add_argument("--snapshot", required=True)
    sp.add_argument("--audit-dir", required=True)
    sp.add_argument("--verification", default=None)
    sp.add_argument("--allowed-list", default=None)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("run-incident", help="run a deterministic incident workflow")
    sp.add_argument("--incident", required=True)
    sp.add_argument("--workspace", default=None)
    sp.set_defaults(func=cmd_run_incident)

    sp = sub.add_parser("web", help="serve the local read-only dashboard")
    add_common(sp)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8787)
    sp.add_argument("--run-demo", action="store_true", help="generate bundled demo output if absent")
    sp.add_argument("--checkpoint-workspace", default=None, help="read-only checkpoint demo artifacts")
    sp.add_argument("--agentteams-v2-workspace", default=None, help="read-only LABOPS-AT-002 evidence bundle")
    sp.add_argument("--agentteams-v3-workspace", default=None, help="read-only LABOPS-AT-003 evidence bundle")
    sp.add_argument("--at004-workspace", default=None, help="read-only LABOPS-AT-004 local or AgentTeams evidence")
    sp.set_defaults(func=cmd_web)

    sp = sub.add_parser("skills", help="inspect the repository-native Skill Registry")
    skill_sub = sp.add_subparsers(dest="action", required=True)
    skill_list = skill_sub.add_parser("list", help="list active Skills")
    skill_list.add_argument("--format", choices=["json"], default="json")
    skill_list.set_defaults(func=cmd_skills)
    skill_describe = skill_sub.add_parser("describe", help="describe one Skill")
    skill_describe.add_argument("skill_id")
    skill_describe.add_argument("--caller-agent-id", default=None)
    skill_describe.add_argument("--format", choices=["json"], default="json")
    skill_describe.set_defaults(func=cmd_skills)
    skill_validate = skill_sub.add_parser("validate", help="validate a Skill invocation input")
    skill_validate.add_argument("skill_id")
    skill_validate.add_argument("input_json")
    skill_validate.add_argument("--caller-agent-id", default=None)
    skill_validate.add_argument("--format", choices=["json"], default="json")
    skill_validate.set_defaults(func=cmd_skills)
    skill_validate_output = skill_sub.add_parser("validate-output", help="validate a Skill output contract")
    skill_validate_output.add_argument("skill_id")
    skill_validate_output.add_argument("output_json")
    skill_validate_output.add_argument("--caller-agent-id", default=None)
    skill_validate_output.add_argument("--format", choices=["json"], default="json")
    skill_validate_output.set_defaults(func=cmd_skills)
    skill_validate_event = skill_sub.add_parser(
        "validate-event", help="validate, but never create, a live AgentTeams Skill usage event"
    )
    skill_validate_event.add_argument("event_json")
    skill_validate_event.add_argument("--format", choices=["json"], default="json")
    skill_validate_event.set_defaults(func=cmd_skills)

    sp = sub.add_parser("trust", help="emit the read-only Trust Layer snapshot")
    sp.add_argument("--at004-root", default=None)
    sp.add_argument("--at002-root", default=None)
    sp.add_argument("--format", choices=["json"], default="json")
    sp.set_defaults(func=cmd_trust)

    sp = sub.add_parser("demo-readiness", help="read-only preflight for the real AgentTeams recording workflow")
    sp.add_argument("--service-checks", action="store_true", help="check Docker, Runner Gateway and Dashboard")
    sp.add_argument("--show-prompt", action="store_true", help="include the exact AT-004 Manager Prompt")
    sp.add_argument("--gateway-url", default="http://127.0.0.1:18103/healthz")
    sp.add_argument("--dashboard-url", default="http://127.0.0.1:8787/healthz")
    sp.set_defaults(func=cmd_demo_readiness)

    sp = sub.add_parser("live-demo", help="prepare or verify a non-formal real AgentTeams live session")
    live_sub = sp.add_subparsers(dest="action", required=True)
    for action_name in ("prepare", "verify"):
        live = live_sub.add_parser(action_name)
        live.add_argument("--session", required=True, help="isolated session ID in YYYYMMDD-NNN format")
        live.add_argument(
            "--sessions-root",
            default=None,
            help="session storage root (default: demo/live-sessions)",
        )
        live.set_defaults(func=cmd_live_demo)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # fix dry_run default override
    args.dry_run = not getattr(args, "no_dry_run", False)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
