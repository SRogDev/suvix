"""Unit tests for suvix.sampling.uniform (deterministic, no media needed)."""

import pytest

from suvix.errors import MediaProcessingError
from suvix.sampling.uniform import uniform_timestamps


def test_evenly_spaced_without_interval():
    assert uniform_timestamps(duration_seconds=10.0, max_frames=4) == [0.0, 2.5, 5.0, 7.5]


def test_deterministic_same_inputs_same_outputs():
    first = uniform_timestamps(duration_seconds=9.0, max_frames=5)
    second = uniform_timestamps(duration_seconds=9.0, max_frames=5)
    assert first == second


def test_single_frame_gives_timestamp_zero():
    assert uniform_timestamps(duration_seconds=10.0, max_frames=1) == [0.0]


def test_interval_mode_steps_by_interval():
    assert uniform_timestamps(
        duration_seconds=10.0, max_frames=100, interval_seconds=3.0
    ) == [0.0, 3.0, 6.0, 9.0]


def test_interval_mode_excludes_timestamp_at_duration():
    # 9.0 would equal duration, not fall strictly below it.
    assert uniform_timestamps(
        duration_seconds=9.0, max_frames=100, interval_seconds=3.0
    ) == [0.0, 3.0, 6.0]


def test_interval_mode_capped_by_max_frames():
    assert uniform_timestamps(
        duration_seconds=10.0, max_frames=2, interval_seconds=3.0
    ) == [0.0, 3.0]


def test_interval_mode_duration_shorter_than_interval():
    assert uniform_timestamps(
        duration_seconds=1.0, max_frames=5, interval_seconds=3.0
    ) == [0.0]


def test_zero_duration_raises():
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=0.0, max_frames=4)


def test_negative_duration_raises():
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=-2.0, max_frames=4)


def test_max_frames_below_one_raises():
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=10.0, max_frames=0)


def test_nonpositive_interval_raises():
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=10.0, max_frames=4, interval_seconds=0.0)
