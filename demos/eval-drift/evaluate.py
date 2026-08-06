"""Evaluate the fixed AT-004 model under one preprocessing profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from metric import accuracy
from model import build_model
from preprocessing import apply_profile


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_run(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir).resolve()
    config_path = run_dir / "eval_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    evaluation = config["evaluation"]
    checkpoint_path = (run_dir / config["checkpoint"]).resolve()
    data_path = (run_dir / config["validation_data"]).resolve()
    if not _inside(checkpoint_path, run_dir) or not _inside(data_path, run_dir):
        raise PermissionError("evaluation input escapes run directory")
    if checkpoint_path.suffix != ".pt" or data_path.suffix != ".pt":
        raise ValueError("checkpoint and validation data must use .pt fixtures")

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    validation = torch.load(data_path, map_location="cpu", weights_only=True)
    model = build_model()
    model.load_state_dict(checkpoint["model_state"])
    features = apply_profile(
        validation["features"],
        evaluation["preprocessing_profile"],
        augmentation_seed=int(evaluation["augmentation_seed"]),
        noise_std=float(evaluation["noise_std"]),
    )
    model.eval()
    with torch.no_grad():
        value = accuracy(model(features), validation["labels"])

    source = Path(__file__).resolve().parent
    return {
        "schema_version": "1.0",
        "accuracy": value,
        "preprocessing_profile": evaluation["preprocessing_profile"],
        "sample_count": int(validation["labels"].numel()),
        "checkpoint_sha256": _sha256(checkpoint_path),
        "validation_data_sha256": _sha256(data_path),
        "metric_file_sha256": _sha256(source / "metric.py"),
        "evaluation_protocol_sha256": _sha256(source / "evaluation_protocol.yaml"),
        "device": "cpu",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evaluate_run(args.run_dir)
    text = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

