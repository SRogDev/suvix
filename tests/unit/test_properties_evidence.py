"""Property-based tests for evidence / semantic validation.

Pure Python only: no ffmpeg, no network, no I/O.

Tolerance note (invariant corrected after reading the real API): the task
wording "timestamps > duration rejected" is imprecise for this codebase.
Both ``validate_evidence`` and ``validate_semantics`` accept timestamps
up to ``duration + tolerance`` (default tolerance 0.5s) and only reject
beyond that. The properties below assert the real contract: inside
``[0, duration + tolerance]`` accepted, beyond it rejected, negative
always rejected.

Interval note: ``EvidenceRef`` is a pydantic model that itself rejects
``start > end`` at construction, so for evidence refs the rejection
property is a ``ValidationError`` on construction; the dict-based
semantic validator reports ``semantic_interval_invalid`` instead.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from suvix.contracts import EvidenceRef
from suvix.evidence import validate_evidence, validate_evidence_timestamps
from suvix.media.frames import FrameRegistry
from suvix.validation import SemanticContext, validate_semantics

MAX_EXAMPLES = 60
TOLERANCE = 0.5  # default in validate_evidence / SemanticContext

durations = st.floats(min_value=0.5, max_value=10_000.0, allow_nan=False, allow_infinity=False)
fractions = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
positive_deltas = st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)


def _codes(issues):
    return [issue.code for issue in issues]


def _registry(mapping: dict[str, float]) -> FrameRegistry:
    registry = FrameRegistry()
    for frame_id, timestamp in mapping.items():
        registry.register(frame_id, timestamp)
    return registry


# --- validate_evidence: acceptance ------------------------------------------


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, fraction=fractions)
def test_evidence_timestamp_within_duration_accepted(duration, fraction):
    ref = EvidenceRef(timestamp_seconds=fraction * duration)
    assert validate_evidence([ref], video_duration_seconds=duration) == []
    assert validate_evidence_timestamps([ref]) == []


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, start_fraction=fractions, end_fraction=fractions)
def test_evidence_interval_within_duration_accepted(duration, start_fraction, end_fraction):
    lo, hi = sorted((start_fraction * duration, end_fraction * duration))
    ref = EvidenceRef(ref_type="segment", start_seconds=lo, end_seconds=hi)
    assert validate_evidence([ref], video_duration_seconds=duration) == []


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, fraction=fractions)
def test_evidence_timestamp_within_tolerance_accepted(duration, fraction):
    # In (duration, duration + tolerance]: accepted by the real contract.
    ref = EvidenceRef(timestamp_seconds=duration + fraction * TOLERANCE)
    assert "evidence_out_of_range" not in _codes(
        validate_evidence([ref], video_duration_seconds=duration)
    )


# --- validate_evidence: rejection -------------------------------------------


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, delta=positive_deltas)
def test_evidence_negative_timestamp_rejected(duration, delta):
    ref = EvidenceRef(timestamp_seconds=-delta)
    codes = _codes(validate_evidence([ref], video_duration_seconds=duration))
    assert "evidence_timestamp_invalid" in codes


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, delta=positive_deltas)
def test_evidence_timestamp_beyond_duration_plus_tolerance_rejected(duration, delta):
    ref = EvidenceRef(timestamp_seconds=duration + TOLERANCE + delta)
    codes = _codes(validate_evidence([ref], video_duration_seconds=duration))
    assert "evidence_out_of_range" in codes


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(end=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False), delta=positive_deltas)
def test_evidence_interval_start_after_end_rejected_at_construction(end, delta):
    with pytest.raises(ValidationError):
        EvidenceRef(start_seconds=end + delta, end_seconds=end)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(end=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False), delta=positive_deltas)
def test_semantics_interval_start_after_end_rejected(end, delta):
    issues = validate_semantics({"start_seconds": end + delta, "end_seconds": end})
    assert "semantic_interval_invalid" in _codes(issues)


# --- Frame references ---------------------------------------------------------


@st.composite
def known_and_unknown_ids(draw):
    known = draw(
        st.lists(
            st.text(alphabet="abcde_0123456789", min_size=1, max_size=10),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )
    unknown = draw(st.text(alphabet="xyz-987", min_size=1, max_size=10))
    return known, unknown


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(pair=known_and_unknown_ids(), duration=durations, fraction=fractions)
def test_evidence_frame_refs_resolve_only_when_registered(pair, duration, fraction):
    known_ids, unknown_id = pair
    registry = _registry({fid: fraction * duration for fid in known_ids})
    for fid in known_ids:
        ref = EvidenceRef(ref_type="frame", timestamp_seconds=0.0, frame_id=fid)
        assert validate_evidence([ref], frame_registry=registry) == []
    if unknown_id not in known_ids:
        ref = EvidenceRef(ref_type="frame", timestamp_seconds=0.0, frame_id=unknown_id)
        codes = _codes(validate_evidence([ref], frame_registry=registry))
        assert "evidence_unknown_frame" in codes


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(pair=known_and_unknown_ids())
def test_semantics_frame_refs_resolve_only_when_registered(pair):
    known_ids, unknown_id = pair
    registry = _registry(dict.fromkeys(known_ids, 1.0))
    context = SemanticContext(frame_registry=registry)
    for fid in known_ids:
        assert validate_semantics({"frame_id": fid}, context=context) == []
    if unknown_id not in known_ids:
        codes = _codes(validate_semantics({"frame_id": unknown_id}, context=context))
        assert "semantic_unknown_frame_ref" in codes


# --- validate_semantics over plain data ---------------------------------------


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, fraction=fractions)
def test_semantics_timestamp_within_duration_accepted(duration, fraction):
    value = fraction * duration
    data = {"events": [{"timestamp_seconds": value}]}
    context = SemanticContext(video_duration_seconds=duration)
    assert validate_semantics(data, context=context) == []


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(delta=positive_deltas)
def test_semantics_negative_timestamp_rejected(delta):
    issues = validate_semantics({"timestamp_seconds": -delta})
    assert "semantic_timestamp_invalid" in _codes(issues)


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, delta=positive_deltas)
def test_semantics_timestamp_beyond_duration_plus_tolerance_rejected(duration, delta):
    value = duration + TOLERANCE + delta
    context = SemanticContext(video_duration_seconds=duration)
    issues = validate_semantics({"timestamp_seconds": value}, context=context)
    assert "semantic_timestamp_out_of_range" in _codes(issues)


# --- Duplicates -----------------------------------------------------------------


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(duration=durations, fraction=fractions)
def test_evidence_duplicate_refs_produce_single_warning(duration, fraction):
    ref = EvidenceRef(timestamp_seconds=fraction * duration)
    issues = validate_evidence(
        [ref, ref.model_copy(deep=True)], video_duration_seconds=duration
    )
    assert _codes(issues) == ["evidence_duplicate"]
    assert issues[0].severity == "warning"
