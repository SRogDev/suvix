"""Deterministic uniform sampling of frame timestamps.

Two modes:
- ``interval_seconds`` given: ``[0, interval, 2*interval, ...]`` while strictly
  below ``duration_seconds``, capped at ``max_frames`` items.
- otherwise: ``max_frames`` timestamps evenly spread over the duration, i.e.
  ``[i * duration_seconds / max_frames for i in range(max_frames)]``.

Timestamps keep full floating-point precision; callers that display or compare
them should round to milliseconds themselves. Uniform sampling makes no claim
about capturing brief events between samples.
"""

from __future__ import annotations

import math

from suvix.errors import MediaProcessingError


def uniform_timestamps(
    *,
    duration_seconds: float,
    max_frames: int,
    interval_seconds: float | None = None,
) -> list[float]:
    """Return ascending sample timestamps in seconds."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise MediaProcessingError(
            f"duration_seconds must be positive, got {duration_seconds}",
            details={"duration_seconds": duration_seconds},
        )
    if max_frames < 1:
        raise MediaProcessingError(
            f"max_frames must be at least 1, got {max_frames}",
            details={"max_frames": max_frames},
        )

    if interval_seconds is not None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise MediaProcessingError(
                f"interval_seconds must be positive, got {interval_seconds}",
                details={"interval_seconds": interval_seconds},
            )
        # Index multiplication, not repeated addition: accumulating
        # t += interval drifts off the i*interval grid (e.g. interval=0.1
        # over 1.0s accumulated to 0.9999999999999999 at i=10, emitting a
        # spurious 11th timestamp just inside the duration). Multiplication
        # keeps every timestamp exactly on the grid, like count mode.
        # Note: pairwise gaps can still sit one ulp below the interval —
        # the interval itself is not exactly representable in binary
        # floating point; the grid values are the contract, not the gaps.
        timestamps: list[float] = []
        i = 0
        while len(timestamps) < max_frames:
            t = i * interval_seconds
            if t >= duration_seconds:
                break
            timestamps.append(t)
            i += 1
        return timestamps

    return [i * duration_seconds / max_frames for i in range(max_frames)]
