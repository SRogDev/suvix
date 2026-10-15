"""Selected-frames strategy (M5): single-pass path through the fake adapter,
against the REAL M2 media layer (ffmpeg-generated clips).

Pins the orchestration behavior: media inspection, bounded uniform sampling,
frame-id evidence honesty, and the same normalize -> validate -> bounded
recovery flow as the native branch.
"""

import shutil

import pytest

from suvix import Suvix
from suvix import extraction as extraction_mod
from suvix.adapters.base import ExtractorCapabilities
from suvix.adapters.fake import FakeExtractor
from suvix.errors import (
    MediaProcessingError,
    SchemaValidationError,
    UnsupportedMediaError,
    UnsupportedStrategyError,
)
from suvix.media.frames import make_frame_id
from suvix.media.metadata import VideoMetadata
from suvix.options import ExtractionOptions
from suvix.sampling.uniform import uniform_timestamps

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not available",
)

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

GOOD = {"events": [{"timestamp_seconds": 2.5, "event_type": "goal"}]}

IMAGE_ONLY_CAPS = ExtractorCapabilities(
    provider="fake",
    model="fake-img-1",
    native_video=False,
    image_input=True,
    multi_image=True,
    structured_output=True,
    usage_metadata=True,
    timestamp_support=True,
    notes="Image-only test double; native video unsupported.",
)

CLIP_DURATION = 4.0  # tests/unit/conftest.py clip_path fixture


def _image_only_fake(script):
    return FakeExtractor(script=script, capabilities=IMAGE_ONLY_CAPS)


def _single_pass_options(**overrides):
    opts = dict(max_refinement_rounds=0)
    opts.update(overrides)
    return ExtractionOptions(**opts)


async def test_auto_selects_selected_frames_for_image_only_adapter(clip_path):
    fake = _image_only_fake([{"data": GOOD}])
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_single_pass_options())

    assert result.execution.strategy == "selected_frames"
    assert "image input" in result.execution.strategy_reason
    assert result.data == GOOD
    assert result.validation.valid is True


async def test_explicit_selected_frames_strategy_with_native_capable_adapter(
    clip_path,
):
    fake = FakeExtractor(script=[{"data": GOOD}])  # native_video=True default
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=ExtractionOptions(strategy="selected_frames",
                                  max_refinement_rounds=0))

    assert result.execution.strategy == "selected_frames"
    assert result.data == GOOD


async def test_single_pass_samples_frames_and_records_usage(clip_path):
    fake = _image_only_fake([{"data": GOOD}])
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_single_pass_options(max_frames=8, coarse_interval_seconds=1.0))

    expected_ts = uniform_timestamps(duration_seconds=CLIP_DURATION, max_frames=8,
                                     interval_seconds=1.0)
    assert expected_ts == [0.0, 1.0, 2.0, 3.0]

    # The adapter received one frame per sampled timestamp, with ids/timestamps.
    (request,) = fake.calls
    assert request.strategy == "selected_frames"
    assert request.frames is not None
    assert len(request.frames) == len(expected_ts)
    for index, frame in enumerate(request.frames):
        # Frame ids are self-consistent with the registry (built from the
        # frame's own verified timestamp) and timestamps match the plan.
        assert frame.frame_id == make_frame_id(index, frame.timestamp_seconds)
        assert frame.timestamp_seconds == pytest.approx(expected_ts[index])
        assert frame.image_bytes  # never empty

    # Execution + usage metadata.
    assert result.execution.frame_count == len(expected_ts)
    assert result.usage.sampled_frames == len(expected_ts)
    assert result.usage.video_duration_seconds == pytest.approx(CLIP_DURATION)
    assert result.usage.provider_requests == 1
    assert result.execution.provider_calls == 1
    assert result.execution.refinement_rounds == 0
    assert result.execution.stages == [
        "validate_inputs", "select_strategy", "inspect_media",
        "sample_frames", "adapter_extract",
    ]


async def test_known_frame_id_evidence_is_kept(clip_path):
    expected_ts = uniform_timestamps(duration_seconds=CLIP_DURATION, max_frames=8,
                                     interval_seconds=1.0)
    known_id = make_frame_id(1, expected_ts[1])
    fake = _image_only_fake([{
        "data": GOOD,
        "evidence": [{"ref_type": "frame", "frame_id": known_id,
                      "timestamp_seconds": expected_ts[1]}],
    }])
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_single_pass_options(max_frames=8, coarse_interval_seconds=1.0))

    assert len(result.evidence) == 1
    assert result.evidence[0].frame_id == known_id
    assert not any("unknown frame_id" in w for w in result.execution.warnings)


async def test_unknown_provider_frame_id_dropped_with_warning(clip_path):
    fake = _image_only_fake([{
        "data": GOOD,
        "evidence": [
            {"ref_type": "frame", "frame_id": "frame-9999-t9.999",
             "timestamp_seconds": 9.999},
            {"ref_type": "provider_reported", "timestamp_seconds": 2.5},
        ],
    }])
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_single_pass_options())

    # Fabricated frame ref dropped; honest provider-reported ref kept.
    assert len(result.evidence) == 1
    assert result.evidence[0].ref_type == "provider_reported"
    assert any(
        w == "provider referenced unknown frame_id 'frame-9999-t9.999'"
        for w in result.execution.warnings
    )


async def test_unknown_duration_raises_unsupported_media(clip_path, monkeypatch):
    async def no_duration(path, *, max_file_bytes=None, max_duration_seconds=None):
        return VideoMetadata(duration_seconds=None, width=320, height=240,
                             fps=30.0, codec="h264", has_audio=False,
                             file_size_bytes=1024)

    monkeypatch.setattr(extraction_mod, "inspect_video", no_duration)
    fake = _image_only_fake([{"data": GOOD}])
    with pytest.raises(UnsupportedMediaError):
        await Suvix().extract(
            video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
            options=_single_pass_options())
    assert fake.calls == []  # no provider call without a sampling plan


async def test_zero_duration_raises_media_processing_error(clip_path, monkeypatch):
    async def zero_duration(path, *, max_file_bytes=None, max_duration_seconds=None):
        return VideoMetadata(duration_seconds=0.0, width=320, height=240,
                             fps=30.0, codec="h264", has_audio=False,
                             file_size_bytes=1024)

    monkeypatch.setattr(extraction_mod, "inspect_video", zero_duration)
    fake = _image_only_fake([{"data": GOOD}])
    with pytest.raises(MediaProcessingError):
        await Suvix().extract(
            video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
            options=_single_pass_options())
    assert fake.calls == []


async def test_frame_budget_exceeded_raises_media_processing_error(
    clip_path, monkeypatch
):
    monkeypatch.setattr(
        extraction_mod, "uniform_timestamps",
        lambda **kwargs: [float(t) for t in range(20)],
    )
    fake = _image_only_fake([{"data": GOOD}])
    with pytest.raises(MediaProcessingError) as exc:
        await Suvix().extract(
            video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
            options=_single_pass_options(max_frames=8))
    assert "frame budget" in str(exc.value).lower()
    assert fake.calls == []


async def test_selected_frames_requires_image_capability():
    caps = ExtractorCapabilities(provider="fake", model="none",
                                 native_video=False, image_input=False)
    fake = FakeExtractor(script=[{"data": GOOD}], capabilities=caps)
    with pytest.raises(UnsupportedStrategyError):
        await Suvix().extract(
            video="clip.mp4", schema=SCHEMA, instructions="x", extractor=fake,
            options=ExtractionOptions(strategy="selected_frames"))


async def test_recovery_repairs_invalid_output_on_selected_frames(clip_path):
    bad = {"events": [{"timestamp_seconds": "soon", "event_type": "goal"}]}
    fake = _image_only_fake([{"data": bad}, {"data": GOOD}])
    result = await Suvix().extract(
        video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_single_pass_options(max_recovery_attempts=1))

    assert result.data == GOOD
    assert result.validation.valid is True
    assert result.execution.recovery_attempts == 1
    assert result.usage.provider_requests == 2
    assert "recovery_attempt_1" in result.execution.stages
    # The repair request kept the sampled frames (same strategy, same frames).
    assert fake.calls[1].frames is not None
    assert len(fake.calls[1].frames) == len(fake.calls[0].frames or [])


async def test_recovery_exhausted_raises_schema_validation_error(clip_path):
    bad = {"events": "not-a-list"}
    fake = _image_only_fake([{"data": bad}, {"data": bad}])
    with pytest.raises(SchemaValidationError):
        await Suvix().extract(
            video=clip_path, schema=SCHEMA, instructions="x", extractor=fake,
            options=ExtractionOptions(max_refinement_rounds=0,
                                      max_recovery_attempts=0,
                                      enable_recovery=False))
