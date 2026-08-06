"""Allowlisted evaluation preprocessing profiles."""

from __future__ import annotations

import torch


PROFILES = {"eval_standard", "train_augmented"}


def apply_profile(features: torch.Tensor, profile: str, *, augmentation_seed: int, noise_std: float) -> torch.Tensor:
    if profile not in PROFILES:
        raise ValueError(f"unsupported preprocessing profile: {profile}")
    if profile == "eval_standard":
        return features.clone()
    generator = torch.Generator().manual_seed(augmentation_seed)
    noise = torch.randn(features.shape, generator=generator, dtype=features.dtype)
    return features + noise_std * noise

