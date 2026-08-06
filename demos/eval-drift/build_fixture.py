"""Build the deterministic, offline LABOPS-AT-004 fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from evaluate import evaluate_run
from model import FEATURE_COUNT, REFERENCE_WEIGHT, reference_state_dict


DATA_SEED = 20260804
AUGMENTATION_SEED = 77
LABEL_NOISE_STD = 0.30
DRIFT_NOISE_STD = 1.35
SAMPLE_COUNT = 640


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def build(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    (output / "checkpoints").mkdir(exist_ok=True)
    generator = torch.Generator().manual_seed(DATA_SEED)
    features = torch.randn(SAMPLE_COUNT, FEATURE_COUNT, generator=generator)
    label_noise = LABEL_NOISE_STD * torch.randn(SAMPLE_COUNT, generator=generator)
    labels = ((features @ REFERENCE_WEIGHT + label_noise) > 0).long()
    checkpoint_path = output / "checkpoints" / "reference.pt"
    data_path = output / "validation_data.pt"
    torch.save({"model_state": reference_state_dict(), "kind": "reference-linear", "seed": DATA_SEED}, checkpoint_path)
    torch.save({"features": features, "labels": labels, "seed": DATA_SEED}, data_path)

    current = {
        "checkpoint": "checkpoints/reference.pt",
        "validation_data": "validation_data.pt",
        "metric": "accuracy",
        "evaluation": {
            "preprocessing_profile": "train_augmented",
            "augmentation_seed": AUGMENTATION_SEED,
            "noise_std": DRIFT_NOISE_STD,
        },
    }
    historical = json.loads(json.dumps(current))
    historical["evaluation"]["preprocessing_profile"] = "eval_standard"
    _write(output / "eval_config.json", current)
    _write(output / "historical_eval_config.json", historical)

    current_values = [evaluate_run(output)["accuracy"] for _ in range(3)]
    _write(output / "eval_config.json", historical)
    historical_values = [evaluate_run(output)["accuracy"] for _ in range(3)]
    _write(output / "eval_config.json", current)

    source = Path(__file__).resolve().parent
    record = {
        "schema_version": "1.0",
        "data_seed": DATA_SEED,
        "current_accuracy_values": current_values,
        "historical_accuracy_values": historical_values,
        "current_profile": "train_augmented",
        "historical_profile": "eval_standard",
        "hashes": {
            "checkpoint": _sha256(checkpoint_path),
            "validation_data": _sha256(data_path),
            "metric": _sha256(source / "metric.py"),
            "evaluation_protocol": _sha256(source / "evaluation_protocol.yaml"),
        },
    }
    _write(output / "historical_baseline.json", record)
    _write(output / "recent_git_diff.json", {
        "changed_fields": ["evaluation.preprocessing_profile"],
        "before": "eval_standard",
        "after": "train_augmented",
        "checkpoint_changed": False,
        "validation_data_changed": False,
        "metric_changed": False,
    })
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(args.output).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

