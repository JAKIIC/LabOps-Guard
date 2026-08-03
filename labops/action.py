"""Controlled action executor.

Default dry-run; command allowlist; workspace boundary; timeout; output
truncation + redaction. Risk actions are SIMULATED (no real execution of
install/download/train). Forbidden actions refused even if approved.

REAL for benign ops; SIMULATED for risky ops.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

# Allowlist of safe commands that may run REAL.
ALLOWLIST = {
    "hash", "list", "read", "cat", "ls", "stat", "wc", "head",
    "python3 --version", "python --version", "echo",
}

# Commands that are SIMULATED in P0 (never executed for real).
SIMULATED_PREFIXES = (
    "pip install", "pip3 install", "wget", "curl", "git clone",
    "python baseline.py", "python3 baseline.py", "train", "download",
)

MAX_OUTPUT_CHARS = 2000
REDACT_PATTERNS = ["password", "secret", "token", "api_key", "authorization"]


def redact(text: str) -> str:
    low = text.lower()
    for pat in REDACT_PATTERNS:
        if pat in low:
            # replace whole line containing the pattern
            lines = text.splitlines(keepends=True)
            out = []
            for ln in lines:
                if pat in ln.lower():
                    out.append("[REDACTED]\n")
                else:
                    out.append(ln)
            text = "".join(out)
    return text


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n...[truncated {len(text)-limit} chars]"
    return text


def _inside_boundary(workdir: Path, workspace: Path) -> bool:
    try:
        workdir.resolve().relative_to(workspace.resolve())
        return True
    except ValueError:
        return False


class ActionResult:
    def __init__(self, status: str, dry_run: bool, simulated: bool, output: str = "",
                 error: str | None = None):
        self.status = status
        self.dry_run = dry_run
        self.simulated = simulated
        self.output = output
        self.error = error

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "simulated": self.simulated,
            "output": self.output,
            "error": self.error,
        }


def execute_action(
    action_id: str,
    command: str,
    workspace: str | Path,
    workdir: str | Path | None = None,
    dry_run: bool = True,
    timeout_seconds: int = 60,
    simulated: bool | None = None,
    trace=None,
) -> ActionResult:
    """Execute a controlled action with safety guards.

    - Forbidden action class -> ActionForbiddenError even if approved.
    - dry_run default True: only prints the command, does not run.
    - Risky commands are SIMULATED (recorded intent, not executed).
    - workdir must stay within workspace boundary.
    """
    workspace = Path(workspace)
    workdir = Path(workdir) if workdir else workspace
    if not _inside_boundary(workdir, workspace):
        raise PermissionError(f"workdir {workdir} outside workspace boundary {workspace}")

    # forbidden heuristic (defense in depth, even if approval said ok)
    low = command.lower()
    forbidden_markers = [
        "test_codeword_x_private", "test_noisy_y_public", "train_codeword_x_shard",
        "train_noisy_y_shard", "submit_sample.csv", ".npz", ".pt", ".pem", ".key",
        "sudo", "chmod", "rm -rf", "del /",
    ]
    if any(m in low for m in forbidden_markers):
        if trace:
            trace.append("action", action_id, "forbidden",
                         from_state="PENDING", to_state="FORBIDDEN",
                         extra={"command": command})
        raise PermissionError(f"action {action_id} is forbidden: {command}")

    # determine simulation: risky prefix -> simulated
    is_simulated = simulated if simulated is not None else low.startswith(SIMULATED_PREFIXES)

    if trace:
        trace.append("action", action_id, "dry_run" if dry_run else "executing",
                     from_state="PENDING",
                     to_state="DRY_RUN" if dry_run else "EXECUTING",
                     extra={"command": command, "simulated": is_simulated})

    if dry_run:
        return ActionResult("DRY_RUN", dry_run=True, simulated=is_simulated,
                            output=f"[dry-run] would run: {command}")

    if is_simulated:
        result = ActionResult(
            "SUCCEEDED", dry_run=False, simulated=True,
            output=f"[SIMULATED] intent recorded, NOT executed: {command}\n"
                   "Simulated actions do NOT modify real system or claim to fix anything.",
        )
        if trace:
            trace.append("action", action_id, "simulated_succeeded",
                         from_state="EXECUTING", to_state="SUCCEEDED",
                         extra={"command": command})
        return result

    # REAL benign command from allowlist
    parts = shlex.split(command)
    if not parts or parts[0] not in ALLOWLIST and command not in ALLOWLIST:
        if trace:
            trace.append("action", action_id, "forbidden",
                         from_state="EXECUTING", to_state="FORBIDDEN",
                         extra={"command": command, "reason": "not in allowlist"})
        return ActionResult("FORBIDDEN", dry_run=False, simulated=False,
                            error=f"command not in allowlist: {command}")

    start = time.time()
    try:
        proc = subprocess.run(
            parts, cwd=str(workdir), capture_output=True, text=True,
            timeout=timeout_seconds,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        out = truncate(redact(out))
        status = "SUCCEEDED" if proc.returncode == 0 else "FAILED"
        if trace:
            trace.append("action", action_id, status.lower(),
                         from_state="EXECUTING", to_state=status,
                         extra={"returncode": proc.returncode})
        return ActionResult(status, dry_run=False, simulated=False, output=out,
                            error=None if proc.returncode == 0 else f"exit {proc.returncode}")
    except subprocess.TimeoutExpired:
        if trace:
            trace.append("action", action_id, "timeout",
                         from_state="EXECUTING", to_state="TIMEOUT",
                         extra={"timeout_seconds": timeout_seconds})
        return ActionResult("TIMEOUT", dry_run=False, simulated=False,
                            error=f"timed out after {timeout_seconds}s")
    except Exception as e:  # noqa: BLE001
        if trace:
            trace.append("action", action_id, "failed",
                         from_state="EXECUTING", to_state="FAILED",
                         extra={"error": str(e)})
        return ActionResult("FAILED", dry_run=False, simulated=False, error=str(e))


def write_output_file(path: str | Path, content: str, workspace: str | Path,
                      dry_run: bool = True, trace=None) -> ActionResult:
    """Write an output file inside workspace boundary (manual_approval class)."""
    workspace = Path(workspace)
    target = Path(path)
    if not _inside_boundary(target, workspace):
        raise PermissionError(f"target {target} outside workspace boundary {workspace}")
    if dry_run:
        return ActionResult("DRY_RUN", dry_run=True, simulated=False,
                            output=f"[dry-run] would write {len(content)} bytes to {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if trace:
        trace.append("action", "write:" + target.name, "succeeded",
                     from_state="EXECUTING", to_state="SUCCEEDED",
                     extra={"path": str(target)})
    return ActionResult("SUCCEEDED", dry_run=False, simulated=False,
                        output=f"wrote {len(content)} bytes to {target}")
