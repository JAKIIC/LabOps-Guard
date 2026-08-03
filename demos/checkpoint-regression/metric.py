"""Frozen metric contract for DEMO-RCA-001.

The verifier hashes this file. Changing it to manufacture an improvement is a
policy violation, not a valid repair.
"""

from __future__ import annotations

import torch


def accuracy(logits: torch.Tensor, labels: torch.Tensor) -> float:
    predictions = logits.argmax(dim=1)
    return float((predictions == labels).float().mean().item())

