"""Small deterministic reference model for LABOPS-AT-004."""

from __future__ import annotations

import torch
from torch import nn


FEATURE_COUNT = 6
REFERENCE_WEIGHT = torch.tensor([2.2, -1.7, 1.3, 0.8, -0.6, 1.1], dtype=torch.float32)


def build_model() -> nn.Module:
    return nn.Linear(FEATURE_COUNT, 2, bias=False)


def reference_state_dict() -> dict:
    model = build_model()
    with torch.no_grad():
        model.weight.copy_(torch.stack((-REFERENCE_WEIGHT, REFERENCE_WEIGHT)))
    return model.state_dict()

