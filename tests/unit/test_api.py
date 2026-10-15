"""End-to-end pipeline through the fake adapter: success, invalid schema,
provider error, validation failure, bounded recovery, and the selected-frames
strategy (Milestone 5)."""

import shutil

import pytest

from suvix import Suvix
from suvix.adapters.fake import FakeExtractor
from suvix.errors import (
    InvalidInputError,
    MalformedOutputError,
    MissingEvidenceError,
    ProviderRequestError,
    RecoveryExhaustedError,
    SchemaValidationError,
    UnsupportedSchemaError,
)
from suvix.options import ExtractionOptions

SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp_seconds": {"type": "number"},
                    "event_type": {"type": "string"},
                },
                "required": ["timestamp_seconds", "event_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}

GOOD = {"events": [{"timestamp_seconds": 1.5, "event_type": "goal"}]}


async def test_successful_extraction_populates_all_result_sections():
    fake = FakeExtractor(script=[{
        "data": GOOD,
        "evidence": [{"timestamp_seconds": 1.5, "ref_type": "provider_reported"}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }])
    result = await Suvix().extract(
        video="clip.mp4", schema=SCHEMA,
        instructions="Identify each visible event of interest.", extractor=fake)

    assert result.data == GOOD
    assert len(result.evidence) == 1
    assert result.evidence[0].timestamp_seconds == 1.5
    assert result.validation.valid is True
    assert result.usage.input_tokens == 100
    assert result.usage.provider_requests == 1
    assert result.execution.strategy == "native_video"
    assert result.execution.strategy_reason
    assert result.execution.provider == "fake"
    assert result.execution.validation_status == "passed"
    assert result.execution.elapsed_seconds >= 0


async def test_invalid_schema_rejected_before_provider_call():
    fake = FakeExtractor(script=[{"data": GOOD}])
    with pytest.raises(UnsupportedSchemaError):
        await Suvix().extract(video="clip.mp4", schema={"type": "nope"},
                              instructions="x", extractor=fake)
    assert fake.calls == []


async def test_provider_error_propagates_not_silenced():
    fake = FakeExtractor(script=[{"error": ProviderRequestError("boom")}])
    with pytest.raises(ProviderRequestError):
        await Suvix().extract(video="clip.mp4", schema=SCHEMA,
                              instructions="x", extractor=fake)


async def test_rate_limit_surfaces_as_provider_error():
    from suvix.errors import RateLimitError
    fake = FakeExtractor(script=[{"error": RateLimitError("slow down")}])
    with pytest.raises(ProviderRequestError):
        await Suvix().extract(video="clip.mp4", schema=SCHEMA,
                              instructions="x", extractor=fake)


async def test_validation_failure_raises_when_recovery_disabled():
    bad = {"events": [{"timestamp_seconds": "soon", "event_type": "goal"}]}
    fake = FakeExtractor(script=[{"data": bad}])
    with pytest.raises(SchemaValidationError) as exc:
        await Suvix().extract(
            video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
            options=ExtractionOptions(enable_recovery=False))
    assert len(fake.calls) == 1  # no repair call was made
    assert exc.value.details["issues"]


async def test_recovery_repairs_malformed_output_within_budget():
    fake = FakeExtractor(script=[
        {"raw_text": "{not valid json"},
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
        options=ExtractionOptions(max_recovery_attempts=2))
    assert result.validation.valid is True
    assert result.data == GOOD
    assert result.execution.recovery_attempts == 1
    assert result.usage.recovery_requests == 1
    assert result.usage.provider_requests == 2


async def test_recovery_exhausted_raises_clear_error():
    fake = FakeExtractor(script=[
        {"raw_text": "{bad1"},
        {"raw_text": "{bad2"},
        {"raw_text": "{bad3"},
    ])
    with pytest.raises(RecoveryExhaustedError):
        await Suvix().extract(
            video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
            options=ExtractionOptions(max_recovery_attempts=2))
    assert len(fake.calls) == 3  # 1 initial + 2 budgeted repairs, no more


async def test_malformed_output_with_zero_budget_raises_malformed_error():
    fake = FakeExtractor(script=[{"raw_text": "{bad"}])
    with pytest.raises(MalformedOutputError):
        await Suvix().extract(
            video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
            options=ExtractionOptions(max_recovery_attempts=0,
                                      enable_recovery=False))


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not available",
)
async def test_selected_frames_strategy_is_implemented(clip_path):
    # Milestone 5: the selected-frames branch is live against the real M2
    # media layer (ffmpeg-generated clip fixture).
    fake = FakeExtractor(script=[{"data": GOOD}])
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=ExtractionOptions(strategy="selected_frames",
                                  max_refinement_rounds=0))
    assert result.execution.strategy == "selected_frames"
    assert result.data == GOOD
    assert result.usage.sampled_frames > 0
    assert result.usage.video_duration_seconds == pytest.approx(4.0, abs=0.2)


async def test_empty_instructions_rejected():
    fake = FakeExtractor(script=[{"data": GOOD}])
    with pytest.raises(InvalidInputError):
        await Suvix().extract(video="clip.mp4", schema=SCHEMA,
                              instructions="  ", extractor=fake)
    assert fake.calls == []


async def test_non_path_video_rejected():
    fake = FakeExtractor(script=[{"data": GOOD}])
    with pytest.raises(InvalidInputError):
        await Suvix().extract(video=123, schema=SCHEMA,  # type: ignore[arg-type]
                              instructions="x", extractor=fake)
    assert fake.calls == []


async def test_cancellation_is_not_converted_to_empty_result():
    import asyncio

    async def hanging_extract(request):
        await asyncio.sleep(60)

    fake = FakeExtractor()
    fake.extract = hanging_extract  # type: ignore[method-assign]
    task = asyncio.create_task(
        Suvix().extract(video="clip.mp4", schema=SCHEMA,
                        instructions="x", extractor=fake))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.calls == []  # the hanging call never completed; nothing fabricated


async def test_require_evidence_raises_when_none_produced():
    fake = FakeExtractor(script=[{"data": GOOD}])  # no evidence refs
    with pytest.raises(MissingEvidenceError):
        await Suvix().extract(
            video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
            options=ExtractionOptions(require_evidence=True))


async def test_require_evidence_passes_when_evidence_present():
    fake = FakeExtractor(script=[{
        "data": GOOD,
        "evidence": [{"timestamp_seconds": 1.5, "ref_type": "provider_reported"}],
    }])
    result = await Suvix().extract(
        video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
        options=ExtractionOptions(require_evidence=True))
    assert result.validation.valid is True
    assert len(result.evidence) == 1
