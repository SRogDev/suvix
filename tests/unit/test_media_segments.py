"""Unit tests for suvix.media.segments (pure logic, no media needed)."""

import pytest
from pydantic import ValidationError

from suvix.errors import MediaProcessingError
from suvix.media.segments import Segment, split_into_segments, to_global_seconds


def test_split_uneven_leaves_shorter_last_segment():
    segments = split_into_segments(10.0, 4.0)
    assert [(s.segment_id, s.start_seconds, s.end_seconds) for s in segments] == [
        ("seg_000", 0.0, 4.0),
        ("seg_001", 4.0, 8.0),
        ("seg_002", 8.0, 10.0),
    ]


def test_split_exact_division_has_no_remainder():
    segments = split_into_segments(8.0, 4.0)
    assert len(segments) == 2
    assert segments[-1].end_seconds == 8.0


def test_split_covers_whole_duration():
    segments = split_into_segments(7.5, 3.0)
    assert segments[0].start_seconds == 0.0
    assert segments[-1].end_seconds == pytest.approx(7.5)
    for first, second in zip(segments, segments[1:], strict=False):
        assert first.end_seconds == pytest.approx(second.start_seconds)


def test_zero_duration_raises():
    with pytest.raises(MediaProcessingError):
        split_into_segments(0.0, 4.0)


def test_negative_duration_raises():
    with pytest.raises(MediaProcessingError):
        split_into_segments(-1.0, 4.0)


def test_zero_segment_length_raises():
    with pytest.raises(MediaProcessingError):
        split_into_segments(10.0, 0.0)


def test_negative_segment_length_raises():
    with pytest.raises(MediaProcessingError):
        split_into_segments(10.0, -2.0)


# Regression tests for the non-finite bug found by property-based tests:
# With the old ``<= 0`` guards, a NaN duration
# returned [] and an infinite duration looped forever generating segments.


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_duration_raises_regression(bad):
    with pytest.raises(MediaProcessingError):
        split_into_segments(bad, 4.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_segment_length_raises_regression(bad):
    with pytest.raises(MediaProcessingError):
        split_into_segments(10.0, bad)


def test_segment_rejects_start_after_end():
    with pytest.raises(ValidationError):
        Segment(segment_id="seg_000", start_seconds=5.0, end_seconds=3.0)


def test_segment_allows_zero_length():
    seg = Segment(segment_id="seg_000", start_seconds=3.0, end_seconds=3.0)
    assert seg.start_seconds == seg.end_seconds


def test_to_global_seconds_adds_segment_offset():
    seg = Segment(segment_id="seg_001", start_seconds=4.0, end_seconds=8.0)
    assert to_global_seconds(seg, 1.5) == pytest.approx(5.5)


def test_to_global_seconds_boundary_is_allowed():
    seg = Segment(segment_id="seg_001", start_seconds=4.0, end_seconds=8.0)
    assert to_global_seconds(seg, 4.0) == pytest.approx(8.0)
    assert to_global_seconds(seg, 0.0) == pytest.approx(4.0)


def test_to_global_seconds_rejects_negative():
    seg = Segment(segment_id="seg_001", start_seconds=4.0, end_seconds=8.0)
    with pytest.raises(MediaProcessingError):
        to_global_seconds(seg, -0.5)


def test_to_global_seconds_rejects_beyond_segment_end():
    seg = Segment(segment_id="seg_001", start_seconds=4.0, end_seconds=8.0)
    with pytest.raises(MediaProcessingError):
        to_global_seconds(seg, 4.001)
