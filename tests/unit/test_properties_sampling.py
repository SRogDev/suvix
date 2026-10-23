"""Property-based tests for pure sampling / segment / frame-id helpers.

Hypothesis asserts INVARIANTS over generated inputs, not examples.
Pure Python only: no ffmpeg, no network, no I/O. Domains are bounded
(finite, positive magnitudes) so counts and floating-point spacing stay
meaningful; non-finite inputs are tested separately as rejections.

Segment-count note: ``split_into_segments`` accumulates ``start = end``
in floating point, so an exact ``ceil(duration / length)`` count is NOT
an invariant (e.g. 1.0 / 0.1 yields an extra dust-length final segment).
The invariant asserted here is the partition itself: contiguous,
covering, positive lengths bounded by the requested length.
"""

from __future__ import annotations

import math
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from suvix.errors import MediaProcessingError
from suvix.media.frames import FrameRegistry, make_frame_id
from suvix.media.segments import Segment, split_into_segments, to_global_seconds
from suvix.sampling.uniform import uniform_timestamps

MAX_EXAMPLES = 60
EPS = 1e-6

durations = st.floats(min_value=0.01, max_value=3600.0, allow_nan=False, allow_infinity=False)
frame_counts = st.integers(min_value=1, max_value=128)
non_finite = st.sampled_from([math.nan, math.inf, -math.inf])


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, max_frames=frame_counts)
def test_count_mode_invariants(duration, max_frames):
    out = uniform_timestamps(duration_seconds=duration, max_frames=max_frames)
    # Count mode: exact length whenever duration > 0.
    assert len(out) == max_frames
    # Sorted strictly ascending and all inside [0, duration).
    assert out == sorted(out)
    assert all(a < b for a, b in zip(out, out[1:], strict=False))
    assert all(0.0 <= t < duration for t in out)
    assert out[0] == 0.0
    # Even spacing (up to float error).
    if max_frames > 1:
        expected_step = duration / max_frames
        for a, b in zip(out, out[1:], strict=False):
            assert abs((b - a) - expected_step) <= EPS
    # Deterministic: two calls with the same inputs are equal.
    assert uniform_timestamps(duration_seconds=duration, max_frames=max_frames) == out


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(
    duration=durations,
    max_frames=frame_counts,
    interval=st.floats(min_value=0.01, max_value=3600.0, allow_nan=False, allow_infinity=False),
)
def test_interval_mode_invariants(duration, max_frames, interval):
    out = uniform_timestamps(
        duration_seconds=duration, max_frames=max_frames, interval_seconds=interval
    )
    assert 1 <= len(out) <= max_frames
    assert out == sorted(out)
    assert all(0.0 <= t < duration for t in out)
    assert out[0] == 0.0
    # Spacing is the interval, up to accumulated float error.
    for a, b in zip(out, out[1:], strict=False):
        assert b - a >= interval - EPS
        assert abs((b - a) - interval) <= EPS
    assert uniform_timestamps(
        duration_seconds=duration, max_frames=max_frames, interval_seconds=interval
    ) == out


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(bad_duration=st.floats(min_value=-3600.0, max_value=0.0, allow_nan=False))
def test_uniform_nonpositive_duration_always_raises(bad_duration):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=bad_duration, max_frames=4)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(bad_max=st.integers(min_value=-100, max_value=0))
def test_uniform_max_frames_below_one_always_raises(bad_max):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=10.0, max_frames=bad_max)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(bad_interval=st.floats(min_value=-3600.0, max_value=0.0, allow_nan=False))
def test_uniform_nonpositive_interval_always_raises(bad_interval):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=10.0, max_frames=4, interval_seconds=bad_interval)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(bad=non_finite)
def test_uniform_nonfinite_duration_raises(bad):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=bad, max_frames=4)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(bad=non_finite)
def test_uniform_nonfinite_interval_raises(bad):
    with pytest.raises(MediaProcessingError):
        uniform_timestamps(duration_seconds=10.0, max_frames=4, interval_seconds=bad)


# --- Segments ---------------------------------------------------------------


@st.composite
def segments_and_relative(draw):
    start = draw(st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False))
    length = draw(
        st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)
    )
    segment = Segment(segment_id="seg_000", start_seconds=start, end_seconds=start + length)
    fraction = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    return segment, fraction * segment.length_seconds


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(pair=segments_and_relative())
def test_to_global_stays_within_segment_and_round_trips(pair):
    segment, relative = pair
    global_ts = to_global_seconds(segment, relative)
    # Within segment bounds.
    assert segment.start_seconds <= global_ts <= segment.end_seconds
    # Round-trip: subtracting the segment start recovers the offset.
    assert abs((global_ts - segment.start_seconds) - relative) <= EPS


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(
    start=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False),
    length=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    fractions=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False), min_size=2, max_size=6
    ),
)
def test_to_global_is_monotone(start, length, fractions):
    segment = Segment(segment_id="seg_000", start_seconds=start, end_seconds=start + length)
    relatives = sorted(f * segment.length_seconds for f in fractions)
    globals_out = [to_global_seconds(segment, r) for r in relatives]
    assert globals_out == sorted(globals_out)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(pair=segments_and_relative(), delta=st.floats(min_value=0.001, max_value=1000.0))
def test_to_global_rejects_out_of_bounds_offsets(pair, delta):
    segment, _relative = pair
    with pytest.raises(MediaProcessingError):
        to_global_seconds(segment, -delta)
    with pytest.raises(MediaProcessingError):
        to_global_seconds(segment, segment.length_seconds + delta)


@st.composite
def duration_and_segment_length(draw):
    duration = draw(
        st.floats(min_value=0.01, max_value=600.0, allow_nan=False, allow_infinity=False)
    )
    # Bound the segment count so generated cases stay cheap.
    length = draw(
        st.floats(
            min_value=max(0.01, duration / 200.0),
            max_value=600.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return duration, length


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(pair=duration_and_segment_length())
def test_split_partitions_the_duration(pair):
    duration, length = pair
    segments = split_into_segments(duration, length)
    assert segments, "a positive duration must produce at least one segment"
    assert segments[0].start_seconds == 0.0
    assert segments[-1].end_seconds == duration
    # Contiguous and non-overlapping, in order, with sequential ids.
    for index, segment in enumerate(segments):
        assert segment.segment_id == f"seg_{index:03d}"
        assert 0.0 < segment.length_seconds <= length + EPS
    for first, second in zip(segments, segments[1:], strict=False):
        assert first.end_seconds == second.start_seconds
    assert abs(sum(s.length_seconds for s in segments) - duration) <= EPS
    # Count is ceil(duration/length), possibly +1 dust segment from float
    # accumulation (see module docstring); never less, never wildly more.
    assert math.ceil(duration / length) <= len(segments) <= math.ceil(duration / length) + 1


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(bad=non_finite)
def test_split_nonfinite_inputs_raise(bad):
    with pytest.raises(MediaProcessingError):
        split_into_segments(bad, 1.0)
    with pytest.raises(MediaProcessingError):
        split_into_segments(10.0, bad)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(
    bad_duration=st.floats(min_value=-600.0, max_value=0.0, allow_nan=False),
    bad_length=st.floats(min_value=-600.0, max_value=0.0, allow_nan=False),
)
def test_split_nonpositive_inputs_raise(bad_duration, bad_length):
    with pytest.raises(MediaProcessingError):
        split_into_segments(bad_duration, 1.0)
    with pytest.raises(MediaProcessingError):
        split_into_segments(10.0, bad_length)


# --- Frame ids / registry (pure helpers in media/frames.py) ------------------

_FRAME_ID_RE = re.compile(r"^f(\d+)@(\d+\.\d{3})s$")


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(
    index=st.integers(min_value=0, max_value=1_000_000),
    timestamp=st.floats(min_value=0.0, max_value=86_400.0, allow_nan=False, allow_infinity=False),
)
def test_make_frame_id_round_trips_to_millisecond(index, timestamp):
    frame_id = make_frame_id(index, timestamp)
    match = _FRAME_ID_RE.match(frame_id)
    assert match is not None, frame_id
    assert int(match.group(1)) == index
    # The embedded timestamp is the input rounded to milliseconds.
    assert abs(float(match.group(2)) - timestamp) <= 0.0005 + 1e-9
    assert make_frame_id(index, timestamp) == frame_id  # deterministic


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(
    entries=st.lists(
        st.tuples(
            st.text(alphabet="abcdefgh_0123456789", min_size=1, max_size=12),
            st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
        ),
        max_size=20,
        unique_by=lambda entry: entry[0],
    ),
    unknown=st.text(alphabet="xyz-987", min_size=1, max_size=8),
)
def test_frame_registry_round_trip_and_unknown_ids(entries, unknown):
    registry = FrameRegistry()
    for frame_id, timestamp in entries:
        registry.register(frame_id, timestamp)
    for frame_id, timestamp in entries:
        assert registry.lookup(frame_id) == timestamp
    assert registry.known_ids() == [frame_id for frame_id, _ in entries]
    known = {frame_id for frame_id, _ in entries}
    if unknown not in known:
        assert registry.lookup(unknown) is None
