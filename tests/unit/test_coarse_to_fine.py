"""Coarse-to-fine refinement (M5): bounded multi-round selected-frame extraction,
against the REAL M2 media layer (a 40s ffmpeg-generated clip, module-scoped).

Scripted fakes drive the whole loop: the coarse pass returns candidate
intervals under the internal coarse schema, fine rounds return the
developer's schema. Budgets are asserted across rounds, never per round.
"""

import shutil

import pytest
from test_selected_frames import GOOD, IMAGE_ONLY_CAPS, SCHEMA

from suvix import Suvix
from suvix.adapters.fake import FakeExtractor
from suvix.errors import SchemaValidationError
from suvix.options import ExtractionOptions
from suvix.sampling.coarse_to_fine import COARSE_SCHEMA

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not available",
)

LONG_DURATION = 40.0  # tests/unit/conftest.py long_clip_path fixture

# The coarse pass speaks the internal schema; the developer's data must not.
assert "candidate_intervals" in COARSE_SCHEMA["properties"]
assert set(COARSE_SCHEMA["required"]) == {"candidate_intervals"}


def _image_only_fake(script):
    return FakeExtractor(script=script, capabilities=IMAGE_ONLY_CAPS)


def _refine_options(**overrides):
    defaults = dict(max_frames=8, coarse_interval_seconds=5.0,
                    max_refinement_rounds=2)
    defaults.update(overrides)
    return ExtractionOptions(**defaults)


def _coarse_script(intervals):
    return {"data": {"candidate_intervals": intervals}}


async def test_coarse_then_fine_two_calls_and_stages(long_clip_path):
    fake = _image_only_fake([
        _coarse_script([{"start_seconds": 10.0, "end_seconds": 14.0,
                         "reason": "motion"}]),
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_refine_options())

    assert len(fake.calls) == 2
    assert result.data == GOOD
    assert result.validation.valid is True
    assert result.execution.refinement_rounds == 1
    assert result.execution.stages == [
        "validate_inputs", "select_strategy", "inspect_media",
        "sample_frames", "coarse_pass", "refine_round_1",
    ]
    # Coarse used half the budget (4 of 8); fine frames stayed within budget.
    assert result.usage.sampled_frames <= 8
    assert result.execution.frame_count == result.usage.sampled_frames
    assert result.usage.video_duration_seconds == pytest.approx(LONG_DURATION)
    assert result.usage.provider_requests == 2
    assert result.execution.provider_calls == 2


async def test_coarse_schema_never_leaks_into_developer_data(long_clip_path):
    fake = _image_only_fake([
        _coarse_script([{"start_seconds": 10.0, "end_seconds": 14.0}]),
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_refine_options())

    assert "candidate_intervals" not in result.data
    # The coarse adapter call used the internal schema, the fine call the
    # developer's schema.
    assert fake.calls[0].json_schema == COARSE_SCHEMA
    assert fake.calls[1].json_schema == SCHEMA


async def test_coarse_with_no_intervals_falls_back_to_fine_over_coarse_frames(
    long_clip_path,
):
    fake = _image_only_fake([
        _coarse_script([]),
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_refine_options())

    assert len(fake.calls) == 2
    assert result.data == GOOD
    assert result.execution.refinement_rounds == 1
    # The fallback fine pass reused the coarse frames: same frame ids sent.
    coarse_ids = [f.frame_id for f in fake.calls[0].frames or []]
    fine_ids = [f.frame_id for f in fake.calls[1].frames or []]
    assert coarse_ids and coarse_ids == fine_ids
    assert result.usage.sampled_frames == len(coarse_ids)


async def test_invalid_intervals_dropped_with_warnings(long_clip_path):
    fake = _image_only_fake([
        _coarse_script([
            {"start_seconds": 20.0, "end_seconds": 10.0},   # start > end
            {"start_seconds": -5.0, "end_seconds": 3.0},    # out of range
            {"start_seconds": 100.0, "end_seconds": 200.0},  # beyond duration
            {"start_seconds": "soon", "end_seconds": 12.0},  # not a number
            {"start_seconds": 10.0, "end_seconds": 14.0},   # the only valid one
        ]),
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_refine_options())

    assert result.data == GOOD
    dropped = [w for w in result.execution.warnings
               if "candidate interval" in w]
    assert len(dropped) == 4
    # The fine pass sampled inside the expanded valid interval [5, 19]
    # (10-14 expanded by ±5s context), not anywhere else.
    fine_ts = [f.timestamp_seconds for f in fake.calls[1].frames or []]
    assert fine_ts
    assert all(5.0 <= t <= 19.0 for t in fine_ts)


async def test_failed_fine_round_triggers_bounded_second_round(long_clip_path):
    bad = {"events": "not-a-list"}  # fails the developer schema
    fake = _image_only_fake([
        _coarse_script([{"start_seconds": 10.0, "end_seconds": 14.0}]),
        {"data": bad},
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_refine_options(max_refinement_rounds=2))

    assert len(fake.calls) == 3  # coarse + 2 fine rounds
    assert result.data == GOOD
    assert result.execution.refinement_rounds == 2
    assert "refine_round_2" in result.execution.stages
    assert result.usage.sampled_frames <= 8  # budget held across rounds
    assert result.usage.provider_requests == 3


async def test_refinement_rounds_capped_by_max_refinement_rounds(long_clip_path):
    bad = {"events": "not-a-list"}
    fake = _image_only_fake(
        [_coarse_script([{"start_seconds": 10.0, "end_seconds": 14.0}])]
        + [{"data": bad}] * 4
    )
    with pytest.raises(SchemaValidationError):
        await Suvix().extract(
            video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
            options=_refine_options(max_refinement_rounds=2,
                                    enable_recovery=False,
                                    max_recovery_attempts=0))

    # 1 coarse + exactly 2 fine rounds: the loop is bounded, not an agent loop.
    assert len(fake.calls) == 3


async def test_frame_budget_never_exceeded_across_rounds(long_clip_path):
    bad = {"events": "not-a-list"}
    fake = _image_only_fake(
        [_coarse_script([{"start_seconds": 10.0, "end_seconds": 35.0}])]
        + [{"data": bad}] * 5
    )
    with pytest.raises(SchemaValidationError):
        await Suvix().extract(
            video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
            options=_refine_options(max_frames=6, max_refinement_rounds=3,
                                    enable_recovery=False,
                                    max_recovery_attempts=0))

    sent_ids: set[str] = set()
    for call in fake.calls:
        for frame in call.frames or []:
            sent_ids.add(frame.frame_id)
    assert sent_ids
    assert len(sent_ids) <= 6  # every sampled frame, across all rounds


async def test_malformed_coarse_output_falls_back_to_fine(long_clip_path):
    fake = _image_only_fake([
        {"raw_text": "{not json at all"},
        {"data": GOOD},
    ])
    result = await Suvix().extract(
        video=long_clip_path, schema=SCHEMA, instructions="x", extractor=fake,
        options=_refine_options())

    assert len(fake.calls) == 2
    assert result.data == GOOD
    assert any("coarse pass" in w for w in result.execution.warnings)
