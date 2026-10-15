"""Public result contracts: data stays separate from evidence, validation,
usage, and execution metadata."""

import pytest
from pydantic import ValidationError

from suvix.contracts import (
    EvidenceRef,
    ExecutionMetadata,
    ExtractionResult,
    UsageReport,
    ValidationIssue,
    ValidationReport,
)


def test_evidence_ref_defaults_to_provider_reported():
    ref = EvidenceRef(timestamp_seconds=12.5)
    assert ref.ref_type == "provider_reported"
    assert ref.frame_id is None


def test_evidence_ref_rejects_inverted_interval():
    with pytest.raises(ValidationError):
        EvidenceRef(start_seconds=10.0, end_seconds=5.0)


def test_evidence_ref_rejects_non_finite_timestamp():
    with pytest.raises(ValidationError):
        EvidenceRef(timestamp_seconds=float("inf"))


def test_validation_report_shape():
    report = ValidationReport(valid=False, issues=[
        ValidationIssue(code="missing_required_field", message="missing 'events'",
                        field="events"),
    ])
    assert report.valid is False
    assert report.issues[0].severity == "error"


def test_usage_report_defaults_to_unknown():
    usage = UsageReport()
    assert usage.input_tokens is None
    assert usage.provider_requests == 0
    assert usage.estimated_cost_usd is None
    assert usage.cost_basis == "unavailable"


def test_execution_metadata_records_strategy_decision():
    meta = ExecutionMetadata(
        strategy="native_video",
        strategy_reason="adapter supports native video",
        provider="gemini",
        model="gemini-2.5-flash",
    )
    assert meta.recovery_attempts == 0
    assert meta.warnings == []


def test_extraction_result_keeps_data_separate_from_metadata():
    result = ExtractionResult(
        data={"events": []},
        evidence=[],
        validation=ValidationReport(valid=True),
        usage=UsageReport(),
        execution=ExecutionMetadata(
            strategy="native_video", strategy_reason="r",
            provider="p", model="m",
        ),
    )
    assert result.data == {"events": []}
    assert "strategy" not in result.data
