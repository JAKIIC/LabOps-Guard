"""Frozen accuracy definition for LABOPS-AT-004."""

from __future__ import annotations

import torch


def accuracy(logits: torch.Tensor, labels: torch.Tensor) -> float:
    return float((logits.argmax(dim=1) == labels).float().mean().item())

