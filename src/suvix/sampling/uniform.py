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

from suvix.errors import MediaProcessingError


def uniform_timestamps(
    *,
    duration_seconds: float,
    max_frames: int,
    interval_seconds: float | None = None,
) -> list[float]:
    """Return ascending sample timestamps in seconds."""
    if duration_seconds <= 0:
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
        if interval_seconds <= 0:
            raise MediaProcessingError(
                f"interval_seconds must be positive, got {interval_seconds}",
                details={"interval_seconds": interval_seconds},
            )
        timestamps: list[float] = []
        t = 0.0
        while t < duration_seconds and len(timestamps) < max_frames:
            timestamps.append(t)
            t += interval_seconds
        return timestamps

    return [i * duration_seconds / max_frames for i in range(max_frames)]
