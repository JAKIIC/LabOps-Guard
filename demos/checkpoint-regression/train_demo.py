"""Generate deterministic best.pt and regressed last.pt checkpoints."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import torch
from torch import nn

from metric import accuracy
from model import FEATURE_COUNT, build_model, make_dataset


def _state_hash(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        digest.update(name.encode("utf-8"))
        digest.update(state[name].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _evaluate(model: nn.Module, x: torch.Tensor, labels: torch.Tensor) -> float:
    model.eval()
    with torch.no_grad():
        return accuracy(model(x), labels)


def generate_checkpoints(output_dir: str | Path, seed: int = 20260803) -> dict:
    output_dir = Path(output_dir).resolve()
    checkpoints = output_dir / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)

    torch.set_num_threads(1)
    torch.manual_seed(seed)
    train_x, train_y, val_x, val_y = make_dataset(seed)
    model = build_model(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.035)
    loss_fn = nn.CrossEntropyLoss()

    best_accuracy = -1.0
    best_epoch = -1
    best_state: dict[str, torch.Tensor] | None = None
    history: list[dict] = []
    for epoch in range(70):
        model.train()
        optimizer.zero_grad()
        loss = loss_fn(model(train_x), train_y)
        loss.backward()
        optimizer.step()
        val_accuracy = _evaluate(model, val_x, val_y)
        history.append({"epoch": epoch + 1, "loss": round(float(loss.item()), 8), "validation_accuracy": val_accuracy})
        if val_accuracy > best_accuracy:
            best_accuracy = val_accuracy
            best_epoch = epoch + 1
            best_state = copy.deepcopy(model.state_dict())

    if best_state is None:
        raise RuntimeError("training did not produce a checkpoint")

    best_path = checkpoints / "best.pt"
    torch.save({
        "kind": "best",
        "seed": seed,
        "feature_count": FEATURE_COUNT,
        "validation_accuracy": best_accuracy,
        "model_state": best_state,
    }, best_path)

    # Build a deterministic late-stage regression fixture. The perturbation is
    # transparent and reproducible; the incident under test is that evaluation
    # selects this inferior last checkpoint instead of best.pt.
    noise_generator = torch.Generator().manual_seed(seed + 99)
    noise = {
        name: torch.randn(tensor.shape, generator=noise_generator, dtype=tensor.dtype)
        for name, tensor in best_state.items()
    }
    target_last_accuracy = 0.70
    candidates: list[tuple[float, float, dict[str, torch.Tensor]]] = []
    for step in range(1, 121):
        scale = step * 0.025
        candidate_state = {
            name: tensor + scale * noise[name]
            for name, tensor in best_state.items()
        }
        model.load_state_dict(candidate_state)
        candidate_accuracy = _evaluate(model, val_x, val_y)
        candidates.append((abs(candidate_accuracy - target_last_accuracy), candidate_accuracy, candidate_state))
    _, last_accuracy, last_state = min(candidates, key=lambda item: (item[0], item[1]))

    last_path = checkpoints / "last.pt"
    torch.save({
        "kind": "last",
        "seed": seed,
        "feature_count": FEATURE_COUNT,
        "validation_accuracy": last_accuracy,
        "regression_fixture": "deterministic late-stage parameter perturbation",
        "model_state": last_state,
    }, last_path)

    config = {
        "schema_version": "1.0",
        "checkpoint": "checkpoints/last.pt",
        "metric": "accuracy",
        "seed": seed,
    }
    (output_dir / "eval_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    log = {
        "schema_version": "1.0",
        "seed": seed,
        "offline": True,
        "device": "cpu",
        "best_epoch": best_epoch,
        "best_accuracy": best_accuracy,
        "last_accuracy": last_accuracy,
        "best_checkpoint": "checkpoints/best.pt",
        "last_checkpoint": "checkpoints/last.pt",
        "best_state_sha256": _state_hash(best_state),
        "last_state_sha256": _state_hash(last_state),
        "history": history,
    }
    (output_dir / "training_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()
    print(json.dumps(generate_checkpoints(args.output, args.seed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

