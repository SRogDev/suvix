"""Bounded selective recovery: one repair call per attempt, same extractor,
budget enforced by the caller."""

import pytest

from suvix.adapters.base import AdapterRequest, ExtractorCapabilities, ProviderExtraction
from suvix.adapters.fake import FakeExtractor
from suvix.contracts import ValidationIssue, ValidationReport
from suvix.options import ExtractionOptions
from suvix.recovery import build_repair_instructions, is_recoverable, run_recovery_attempt


def _request():
    return AdapterRequest(
        video_path="clip.mp4",
        schema={"type": "object"},
        instructions="Extract events.",
        options=ExtractionOptions(),
        strategy="native_video",
    )


def _failed_report():
    return ValidationReport(valid=False, issues=[
        ValidationIssue(code="schema_violation", message="'events' is required",
                        field="/"),
    ])


def test_repair_instructions_name_the_issues():
    text = build_repair_instructions(_failed_report(), max_issues=5)
    assert "'events' is required" in text
    assert "JSON" in text


def test_repair_instructions_capped():
    report = ValidationReport(valid=False, issues=[
        ValidationIssue(code="c", message=f"issue {i}") for i in range(20)
    ])
    text = build_repair_instructions(report, max_issues=5)
    assert "issue 19" not in text


def test_malformed_output_is_recoverable():
    assert is_recoverable(None, _failed_report()) is True


def test_clean_report_is_not_recoverable():
    assert is_recoverable({"a": 1}, ValidationReport(valid=True)) is False


async def test_recovery_attempt_reuses_same_extractor_and_counts():
    fake = FakeExtractor(script=[{"data": {"events": []}}])
    extraction = await run_recovery_attempt(
        extractor=fake, request=_request(), failed_report=_failed_report())
    assert isinstance(extraction, ProviderExtraction)
    assert extraction.data == {"events": []}
    assert len(fake.calls) == 1
    # The repair request keeps the original schema and strategy.
    assert fake.calls[0].json_schema == {"type": "object"}
    assert fake.calls[0].strategy == "native_video"


async def test_recovery_attempt_propagates_provider_errors():
    from suvix.errors import ProviderRequestError
    fake = FakeExtractor(script=[{"error": ProviderRequestError("down")}])
    with pytest.raises(ProviderRequestError):
        await run_recovery_attempt(
            extractor=fake, request=_request(), failed_report=_failed_report())


def test_fake_extractor_reports_capabilities():
    caps = FakeExtractor().capabilities
    assert isinstance(caps, ExtractorCapabilities)
    assert caps.native_video is True
