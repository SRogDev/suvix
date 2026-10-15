"""Deterministic semantic validation (Milestone 6).

These checks are range/plausibility checks only: they verify that time values
are finite, non-negative, ordered, and within the video duration, and that
frame references resolve in the execution's frame registry.

They never claim semantic truth: code can check that a timestamp falls inside
the clip, not that the model actually saw the event.
"""

from __future__ import annotations

from suvix.validation import SemanticContext, iter_time_fields, validate_semantics


class StubRegistry:
    """Duck-typed frame registry: ``.lookup(frame_id) -> float | None``."""

    def __init__(self, mapping: dict[str, float]):
        self._mapping = mapping

    def lookup(self, frame_id: str) -> float | None:
        return self._mapping.get(frame_id)


def _codes(issues):
    return [issue.code for issue in issues]


def test_negative_timestamp_is_invalid():
    data = {"events": [{"timestamp_seconds": -1.5}]}
    codes = _codes(validate_semantics(data))
    assert "semantic_timestamp_invalid" in codes


def test_nonfinite_timestamp_is_invalid():
    data = {"a": {"start_seconds": float("inf")}, "b": {"end_seconds": float("nan")}}
    issues = validate_semantics(data)
    assert _codes(issues).count("semantic_timestamp_invalid") == 2


def test_timestamp_beyond_duration_is_out_of_range():
    context = SemanticContext(video_duration_seconds=60.0)
    issues = validate_semantics({"timestamp_seconds": 61.0}, context=context)
    assert _codes(issues) == ["semantic_timestamp_out_of_range"]
    # The message must state the tolerance that was applied.
    assert "0.5" in issues[0].message


def test_timestamp_within_tolerance_is_accepted():
    context = SemanticContext(video_duration_seconds=60.0, timestamp_tolerance_seconds=0.5)
    assert validate_semantics({"timestamp_seconds": 60.4}, context=context) == []


def test_custom_tolerance_is_respected():
    context = SemanticContext(video_duration_seconds=60.0, timestamp_tolerance_seconds=2.0)
    assert validate_semantics({"timestamp_seconds": 61.5}, context=context) == []
    issues = validate_semantics({"timestamp_seconds": 62.5}, context=context)
    assert _codes(issues) == ["semantic_timestamp_out_of_range"]


def test_duration_none_skips_range_checks():
    assert validate_semantics({"timestamp_seconds": 99999.0}) == []


def test_start_after_end_is_invalid():
    data = {"segment": {"start_seconds": 10.0, "end_seconds": 5.0}}
    issues = validate_semantics(data)
    assert _codes(issues) == ["semantic_interval_invalid"]
    assert issues[0].field == "/segment"


def test_equal_start_end_is_valid_interval():
    data = {"segment": {"start_seconds": 5.0, "end_seconds": 5.0}}
    assert validate_semantics(data) == []


def test_unknown_frame_ref_is_flagged():
    registry = StubRegistry({"f1": 1.0})
    context = SemanticContext(frame_registry=registry)
    issues = validate_semantics({"frame_id": "f9"}, context=context)
    assert _codes(issues) == ["semantic_unknown_frame_ref"]
    assert issues[0].field == "/frame_id"


def test_known_frame_ref_passes():
    registry = StubRegistry({"f1": 1.0})
    context = SemanticContext(frame_registry=registry)
    assert validate_semantics({"frame_id": "f1"}, context=context) == []


def test_frame_ref_alias_is_also_checked():
    registry = StubRegistry({"f1": 1.0})
    context = SemanticContext(frame_registry=registry)
    issues = validate_semantics({"evidence": {"frame_ref": "nope"}}, context=context)
    assert _codes(issues) == ["semantic_unknown_frame_ref"]
    assert issues[0].field == "/evidence/frame_ref"


def test_no_registry_skips_frame_checks():
    assert validate_semantics({"frame_id": "anything"}) == []


def test_valid_data_has_no_issues():
    registry = StubRegistry({"f1": 1.0, "f2": 2.0})
    context = SemanticContext(video_duration_seconds=60.0, frame_registry=registry)
    data = {
        "events": [
            {"timestamp_seconds": 12.5, "frame_id": "f1"},
            {"start_seconds": 20.0, "end_seconds": 30.0, "frame_ref": "f2"},
        ]
    }
    assert validate_semantics(data, context=context) == []


def test_semantic_context_defaults():
    context = SemanticContext()
    assert context.video_duration_seconds is None
    assert context.timestamp_tolerance_seconds == 0.5
    assert context.frame_registry is None


def test_iter_time_fields_matches_common_conventions():
    data = {
        "timestamp_seconds": 1.0,
        "events": [{"start_seconds": 2.0, "end_seconds": 3.0}],
        "custom_offset_seconds": 4.0,
        "ended_timestamp": 5.0,
        "label": "not a time",
        "duration": "also not a time",
    }
    found = dict(iter_time_fields(data))
    assert found == {
        "/timestamp_seconds": 1.0,
        "/events/0/start_seconds": 2.0,
        "/events/0/end_seconds": 3.0,
        "/custom_offset_seconds": 4.0,
        "/ended_timestamp": 5.0,
    }


def test_iter_time_fields_ignores_non_numeric_values():
    data = {"duration_seconds": "long", "flag_seconds": True, "when_timestamp": None}
    assert list(iter_time_fields(data)) == []
