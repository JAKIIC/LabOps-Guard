"""Deterministic synthetic classification model used by DEMO-RCA-001."""

from __future__ import annotations

import torch
from torch import nn

FEATURE_COUNT = 6
TRAIN_SIZE = 640
VALIDATION_SIZE = 320


def make_dataset(seed: int = 20260803) -> tuple[torch.Tensor, ...]:
    """Create a small, linearly learnable dataset without network or downloads."""
    generator = torch.Generator().manual_seed(seed)
    x = torch.randn(TRAIN_SIZE + VALIDATION_SIZE, FEATURE_COUNT, generator=generator)
    true_weight = torch.tensor([2.2, -1.7, 1.3, 0.8, -0.6, 1.1])
    noise = 0.18 * torch.randn(TRAIN_SIZE + VALIDATION_SIZE, generator=generator)
    labels = ((x @ true_weight + noise) > 0).long()
    return (
        x[:TRAIN_SIZE],
        labels[:TRAIN_SIZE],
        x[TRAIN_SIZE:],
        labels[TRAIN_SIZE:],
    )


def build_model(seed: int = 20260803) -> nn.Module:
    torch.manual_seed(seed)
    return nn.Sequential(
        nn.Linear(FEATURE_COUNT, 12),
        nn.Tanh(),
        nn.Linear(12, 2),
    )

