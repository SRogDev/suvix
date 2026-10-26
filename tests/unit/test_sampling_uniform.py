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


# Regression tests for the non-finite bug found by property-based tests:
# NaN comparisons are all False, so the old
# ``<= 0`` guards let NaN through (returning [nan, ...] / [0.0]) and inf
# produced inf/nan timestamps instead of raising.


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_duration_raises_regression(bad):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=bad, max_frames=4)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_interval_raises_regression(bad):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=10.0, max_frames=4, interval_seconds=bad)


def test_interval_timestamps_stay_on_grid_regression():
    """Regression: repeated-addition accumulation drifted off the grid.

    Found by property testing: with duration=1.0 and interval=0.1 the old
    t += interval loop accumulated to 0.9999999999999999 at i=10 and
    emitted a spurious 11th timestamp just inside the duration. Interval
    timestamps are now computed by index multiplication (i * interval),
    matching the count mode's construction, so the output is exactly the
    grid points strictly below the duration. (Pairwise gaps can still sit
    one ulp below the interval — 0.1 is not exactly representable — so
    the grid values, not the gaps, are the pinned contract.)
    """
    ts = uniform_timestamps(duration_seconds=1.0, max_frames=100,
                            interval_seconds=0.1)
    assert ts == [i * 0.1 for i in range(10)]
    assert all(t < 1.0 for t in ts)
