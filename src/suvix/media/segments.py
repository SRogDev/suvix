"""Video segmentation and segment-relative timestamp conversion.

Segments partition a video duration into consecutive, non-overlapping
intervals. Segment-relative timestamps (e.g. offsets reported inside a
segment) convert to global video timestamps by adding the segment's start.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, model_validator

from suvix.errors import MediaProcessingError


class Segment(BaseModel):
    """One interval of a video, in global seconds."""

    segment_id: str
    start_seconds: float
    end_seconds: float

    @model_validator(mode="after")
    def _check_order(self) -> Segment:
        if self.end_seconds < self.start_seconds:
            raise ValueError(
                f"end_seconds ({self.end_seconds}) must not be before "
                f"start_seconds ({self.start_seconds})"
            )
        return self

    @property
    def length_seconds(self) -> float:
        """Segment length in seconds."""
        return self.end_seconds - self.start_seconds


def split_into_segments(duration_seconds: float, segment_length_seconds: float) -> list[Segment]:
    """Split ``duration_seconds`` into consecutive segments of
    ``segment_length_seconds``. The last segment may be shorter. Segment ids
    are zero-padded: ``seg_000``, ``seg_001``, ...
    """
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise MediaProcessingError(
            f"duration_seconds must be positive, got {duration_seconds}",
            details={"duration_seconds": duration_seconds},
        )
    if not math.isfinite(segment_length_seconds) or segment_length_seconds <= 0:
        raise MediaProcessingError(
            f"segment_length_seconds must be positive, got {segment_length_seconds}",
            details={"segment_length_seconds": segment_length_seconds},
        )
    segments: list[Segment] = []
    start = 0.0
    index = 0
    while start < duration_seconds:
        end = min(start + segment_length_seconds, duration_seconds)
        segments.append(
            Segment(segment_id=f"seg_{index:03d}", start_seconds=start, end_seconds=end)
        )
        start = end
        index += 1
    return segments


def to_global_seconds(segment: Segment, relative_seconds: float) -> float:
    """Convert a segment-relative offset to a global video timestamp."""
    if relative_seconds < 0:
        raise MediaProcessingError(
            f"relative_seconds must be non-negative, got {relative_seconds}",
            details={"relative_seconds": relative_seconds},
        )
    if relative_seconds > segment.length_seconds:
        raise MediaProcessingError(
            f"relative_seconds ({relative_seconds}) exceeds segment length "
            f"({segment.length_seconds})",
            details={
                "relative_seconds": relative_seconds,
                "segment_length_seconds": segment.length_seconds,
            },
        )
    return segment.start_seconds + relative_seconds
