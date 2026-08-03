"""Append-only trace log with hash chaining.

Every state transition / event is appended as one JSON line. Each line carries
the SHA-256 of the previous line, forming an integrity chain. Entries are never
modified or deleted (append-only).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


class TraceLog:
    """Append-only JSONL trace with hash chaining.

    File layout: one JSON object per line. Each record:
      {
        "seq": int,
        "ts": iso8601,
        "entity_type": str,
        "entity_id": str,
        "event": str,
        "from_state": str|None,
        "to_state": str|None,
        "prev_hash": str|None,   # hash of previous raw line
        "hash": str              # sha256 of this raw line
      }
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_line(self) -> str | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        # read last non-empty line
        last = ""
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line:
                    last = line
        return last or None

    def append(
        self,
        entity_type: str,
        entity_id: str,
        event: str,
        from_state: str | None = None,
        to_state: str | None = None,
        extra: dict | None = None,
        actor: str | None = None,
        status: str | None = None,
    ) -> dict:
        import datetime

        prev = self._last_line()
        prev_hash = None
        seq = 0
        if prev is not None:
            try:
                prev_rec = json.loads(prev)
                prev_hash = prev_rec.get("hash")
                seq = int(prev_rec["seq"]) + 1
            except Exception:
                prev_hash = None
                seq = 0
        record = {
            "seq": seq,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event": event,
            "from_state": from_state,
            "to_state": to_state,
            "prev_hash": prev_hash,
        }
        if actor is not None:
            record["actor"] = actor
        if status is not None:
            record["status"] = status
        if extra:
            record["extra"] = extra
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True)
        record["hash"] = _line_hash(raw)
        # write raw line that includes hash for chain continuity
        final = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(final + "\n")
        return record

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line:
                    out.append(json.loads(line))
        return out

    def verify_chain(self) -> tuple[bool, str]:
        """Verify the hash chain integrity of the whole trace."""
        records = self.read()
        prev_hash = None
        for i, rec in enumerate(records):
            expected_prev = prev_hash
            if rec.get("prev_hash") != expected_prev:
                return (False, f"chain break at seq={rec.get('seq')} (expected prev {expected_prev}, got {rec.get('prev_hash')})")
            # recompute hash over the canonical record minus its own hash field
            check = {k: v for k, v in rec.items() if k != "hash"}
            raw = json.dumps(check, ensure_ascii=False, sort_keys=True)
            if _line_hash(raw) != rec.get("hash"):
                return (False, f"hash mismatch at seq={rec.get('seq')}")
            prev_hash = rec.get("hash")
        return (True, f"chain ok, {len(records)} entries")
