"""Evaluate a controlled checkpoint for DEMO-RCA-001."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from metric import accuracy
from model import build_model, make_dataset


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def evaluate_run(run_dir: str | Path, checkpoint: str | None = None) -> dict:
    run_dir = Path(run_dir).resolve()
    config_path = run_dir / "eval_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    checkpoint_value = checkpoint or config["checkpoint"]
    checkpoint_path = (run_dir / checkpoint_value).resolve()
    if not _inside(checkpoint_path, run_dir):
        raise PermissionError("checkpoint escapes run directory")
    if checkpoint_path.suffix != ".pt":
        raise ValueError("only .pt checkpoints are allowed")

    payload = torch.load(checkpoint_path, map_location="cpu")
    model = build_model(int(payload["seed"]))
    model.load_state_dict(payload["model_state"])
    _, _, val_x, val_y = make_dataset(int(payload["seed"]))
    model.eval()
    with torch.no_grad():
        value = accuracy(model(val_x), val_y)

    metric_path = Path(__file__).with_name("metric.py")
    result = {
        "schema_version": "1.0",
        "checkpoint": checkpoint_value.replace("\\", "/"),
        "checkpoint_kind": payload["kind"],
        "accuracy": value,
        "sample_count": int(val_y.numel()),
        "metric_file_sha256": hashlib.sha256(metric_path.read_bytes()).hexdigest(),
        "data_seed": int(payload["seed"]),
        "device": "cpu",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evaluate_run(args.run_dir, args.checkpoint)
    text = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

