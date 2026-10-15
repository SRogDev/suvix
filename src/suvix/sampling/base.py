"""Sampler contract.

A sampler converts a video duration and a resource budget into an ordered list
of timestamps (seconds) at which frames should be extracted. It must be
deterministic: identical inputs always produce identical timestamps.

A sampler only *proposes* timestamps. Whether each timestamp is actually
seekable is verified later during frame extraction (see
``suvix.media.frames``), which records whether the real presentation
timestamp matched the requested one.
"""

from __future__ import annotations

from typing import Protocol


class Sampler(Protocol):
    """Structural interface implemented by sampling strategies."""

    def __call__(self, *, duration_seconds: float, max_frames: int) -> list[float]:
        """Return ascending timestamps in seconds, at most ``max_frames`` items."""
        ...
