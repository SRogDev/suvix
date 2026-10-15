"""Full evidence validation (Milestone 6).

``validate_evidence`` runs the Milestone 1 timestamp checks and adds
duration bounds (with tolerance), frame-registry resolution for ``frame``
refs, and duplicate detection. The old ``validate_evidence_timestamps``
stays intact and is exercised through the new function.
"""

from __future__ import annotations

from suvix.contracts import EvidenceRef
from suvix.evidence import validate_evidence, validate_evidence_timestamps


class StubRegistry:
    """Duck-typed frame registry: ``.lookup(frame_id) -> float | None``."""

    def __init__(self, mapping: dict[str, float]):
        self._mapping = mapping

    def lookup(self, frame_id: str) -> float | None:
        return self._mapping.get(frame_id)


def _codes(issues):
    return [issue.code for issue in issues]


def test_existing_timestamp_checks_still_run():
    refs = [EvidenceRef(timestamp_seconds=-2.0)]
    codes = _codes(validate_evidence(refs))
    assert "evidence_timestamp_invalid" in codes
    # The legacy entry point is unchanged and agrees.
    assert _codes(validate_evidence_timestamps(refs)) == codes


def test_timestamp_beyond_duration_is_out_of_range():
    refs = [EvidenceRef(timestamp_seconds=61.5)]
    issues = validate_evidence(refs, video_duration_seconds=60.0)
    assert _codes(issues) == ["evidence_out_of_range"]
    assert "0.5" in issues[0].message  # tolerance is stated


def test_timestamp_within_tolerance_is_accepted():
    refs = [EvidenceRef(timestamp_seconds=60.4)]
    assert validate_evidence(refs, video_duration_seconds=60.0) == []


def test_interval_end_beyond_duration_is_out_of_range():
    refs = [EvidenceRef(start_seconds=59.0, end_seconds=62.0)]
    assert _codes(validate_evidence(refs, video_duration_seconds=60.0)) == [
        "evidence_out_of_range"
    ]


def test_no_duration_skips_range_checks():
    refs = [EvidenceRef(timestamp_seconds=99999.0)]
    assert validate_evidence(refs) == []


def test_unknown_frame_ref_is_an_error():
    refs = [EvidenceRef(ref_type="frame", timestamp_seconds=1.0, frame_id="f9")]
    issues = validate_evidence(refs, frame_registry=StubRegistry({"f1": 1.0}))
    assert len(issues) == 1
    assert issues[0].code == "evidence_unknown_frame"
    assert issues[0].severity == "error"


def test_known_frame_ref_passes():
    refs = [EvidenceRef(ref_type="frame", timestamp_seconds=1.0, frame_id="f1")]
    assert validate_evidence(refs, frame_registry=StubRegistry({"f1": 1.0})) == []


def test_frame_check_skipped_without_registry():
    refs = [EvidenceRef(ref_type="frame", timestamp_seconds=1.0, frame_id="f9")]
    assert validate_evidence(refs) == []


def test_non_frame_ref_type_ignores_frame_id():
    refs = [EvidenceRef(ref_type="provider_reported", timestamp_seconds=1.0, frame_id="f9")]
    assert validate_evidence(refs, frame_registry=StubRegistry({"f1": 1.0})) == []


def test_duplicate_refs_produce_a_single_warning():
    ref = EvidenceRef(ref_type="segment", start_seconds=1.0, end_seconds=2.0)
    issues = validate_evidence([ref, ref.model_copy(deep=True)])
    assert len(issues) == 1
    assert issues[0].code == "evidence_duplicate"
    assert issues[0].severity == "warning"


def test_triplicate_refs_still_one_warning():
    ref = EvidenceRef(timestamp_seconds=3.0)
    issues = validate_evidence([ref, ref.model_copy(deep=True), ref.model_copy(deep=True)])
    assert [i.code for i in issues] == ["evidence_duplicate"]
    assert all(i.severity == "warning" for i in issues)


def test_distinct_refs_are_not_duplicates():
    refs = [
        EvidenceRef(timestamp_seconds=1.0),
        EvidenceRef(timestamp_seconds=2.0),
        EvidenceRef(timestamp_seconds=1.0, note="different note"),
    ]
    assert validate_evidence(refs) == []
