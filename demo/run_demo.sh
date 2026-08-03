#!/usr/bin/env bash
# LabOps Guard demo runbook — self-contained, portable (REV-2).
# Uses repo-relative demo/fixtures by default; overridable via env:
#   LABOPS_FIXTURES   -> dir containing project_snapshot_lite/, audit/, snapshot_verification.json
#   LABOPS_OUTPUT     -> output workspace dir (default: <repo>/demo/output)
# Safe: dry-run first, risky SIMULATED, no network/install/train, no excluded-data reads.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURES="${LABOPS_FIXTURES:-$ROOT/demo/fixtures}"
SNAPSHOT="$FIXTURES/project_snapshot_lite"
AUDIT="$FIXTURES/audit"
VERIF="$FIXTURES/snapshot_verification.json"
ALLOWED="$ROOT/demo/allowed_files.json"

WS="${LABOPS_OUTPUT:-$ROOT/demo/output}"
rm -rf "$WS"
mkdir -p "$WS"

cd "$ROOT"

echo "############ LabOps Guard Demo (polar-baseline) ############"
echo "fixtures=$FIXTURES"
echo "workspace=$WS"
echo

echo "### Full chain: init -> evidence -> diagnosis -> approval -> action -> verification -> trace"
python3 -B -m labops demo \
  --workspace "$WS" \
  --snapshot "$SNAPSHOT" \
  --audit-dir "$AUDIT" \
  --verification "$VERIF" \
  --allowed-list "$ALLOWED"
echo

echo "### Approval request log"
python3 -B -m labops approve list --workspace "$WS"
echo

echo "### Trace chain verification"
python3 -B -m labops trace --workspace "$WS" --verify
echo

echo "Demo artifacts written under $WS"
find "$WS" -type f | sort
