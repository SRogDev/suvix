"""Tests for the benchmark runner: baselines A-E, metric computation,
output writing, comparability notes, and per-baseline summarization.

All baselines run against scripted FakeExtractors — no network, no keys.
The fake adapter stands in for "provider" behavior; the tests verify the
harness, not provider accuracy.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    VideoExtractor,
)
from suvix.adapters.fake import FakeExtractor
from suvix.evaluation.runner import (
    BASELINES,
    BaselineResult,
    BenchmarkTask,
    run_baseline,
    summarize,
)

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "timestamp_seconds": {"type": "number"},
                },
                "required": ["type", "timestamp_seconds"],
            },
        }
    },
    "required": ["events"],
}

EXPECTED = {
    "events": [
        {"type": "flash", "timestamp_seconds": 2.5},
        {"type": "flash", "timestamp_seconds": 5.5},
    ]
}


def make_task(video_path: str) -> BenchmarkTask:
    return BenchmarkTask(
        task_id="temporal_flashes",
        category="temporal_events",
        video_path=video_path,
        schema=TASK_SCHEMA,
        instructions="Report each visible text flash with its timestamp.",
        expected=EXPECTED,
        time_tolerance_seconds=1.0,
        evaluation_notes="Synthetic fixture: flashes burned in with ffmpeg.",
        known_ambiguities=["Frame-exact flash onset is ambiguous at 15fps."],
    )


def make_factory(data: dict[str, Any]) -> Any:
    def factory(baseline: str) -> VideoExtractor:
        return FakeExtractor(
            provider="fake",
            model="fake-1",
            script=[{"data": data, "usage": {"input_tokens": 100, "output_tokens": 50}}],
        )

    return factory


# ---------------------------------------------------------------------------
# BenchmarkTask contract
# ---------------------------------------------------------------------------


class TestBenchmarkTask:
    def test_requires_video_path_or_ref(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        assert task.video_path == str(video)

    def test_video_ref_alternative(self):
        task = BenchmarkTask(
            task_id="t",
            category="temporal_events",
            video_ref="https://example.com/video.mp4",
            video_sha256="abc123",
            schema=TASK_SCHEMA,
            instructions="x",
            expected=EXPECTED,
        )
        assert task.video_ref == "https://example.com/video.mp4"

    def test_neither_video_path_nor_ref_rejected(self):
        with pytest.raises(ValidationError):
            BenchmarkTask(
                task_id="t",
                category="temporal_events",
                schema=TASK_SCHEMA,
                instructions="x",
                expected=EXPECTED,
            )

    def test_ref_without_sha_rejected(self):
        with pytest.raises(ValidationError):
            BenchmarkTask(
                task_id="t",
                category="temporal_events",
                video_ref="https://example.com/video.mp4",
                schema=TASK_SCHEMA,
                instructions="x",
                expected=EXPECTED,
            )

    def test_baseline_names(self):
        assert BASELINES == (
            "A_direct_native",
            "B_suvix_native",
            "C_suvix_frames",
            "D_suvix_coarse_to_fine",
            "E_direct_frames",
        )


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


class TestBaselines:
    async def test_b_suvix_native_produces_scored_result(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        result = await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(EXPECTED)
        )
        assert isinstance(result, BaselineResult)
        assert result.baseline == "B_suvix_native"
        assert result.task_id == "temporal_flashes"
        assert result.error is None
        assert result.result is not None
        assert result.result.data == EXPECTED
        # Perfect scripted prediction => perfect event F1.
        assert result.metrics["event_f1"] == pytest.approx(1.0)
        assert result.metrics["schema_pass"] == 1.0
        assert result.metrics["provider_requests"] >= 1
        assert result.comparability_notes  # same schema/instructions/video recorded

    async def test_b_imperfect_prediction_scores_below_one(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        predicted = {"events": [{"type": "flash", "timestamp_seconds": 2.5}]}
        result = await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(predicted)
        )
        assert result.metrics["event_recall"] == pytest.approx(0.5)
        assert result.metrics["event_precision"] == pytest.approx(1.0)

    async def test_b_adapter_error_becomes_error_result(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))

        def factory(baseline: str) -> VideoExtractor:
            return FakeExtractor(
                provider="fake",
                model="fake-1",
                script=[{"error": RuntimeError("provider exploded")}],
            )

        result = await run_baseline(task, "B_suvix_native", extractor_factory=factory)
        assert result.result is None
        assert "provider exploded" in result.error
        assert result.metrics == {}

    async def test_a_direct_native_bypasses_suvix_orchestration(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        extractor = FakeExtractor(
            provider="fake",
            model="fake-1",
            script=[{"data": EXPECTED, "usage": {"input_tokens": 10}}],
        )

        def factory(baseline: str) -> VideoExtractor:
            return extractor

        result = await run_baseline(task, "A_direct_native", extractor_factory=factory)
        assert result.error is None
        assert result.result is not None
        # Direct adapter call: exactly one adapter call, no recovery stages.
        assert len(extractor.calls) == 1
        assert isinstance(extractor.calls[0], AdapterRequest)
        assert result.result.execution.stages == ["adapter_extract"]
        assert any("bypass" in note for note in result.comparability_notes)
        assert result.metrics["event_f1"] == pytest.approx(1.0)

    async def test_c_suvix_frames_runs_selected_frames(self, long_clip_path):
        # Milestones 5/8: baseline C runs the real selected-frames pipeline.
        task = make_task(str(long_clip_path))
        result = await run_baseline(
            task, "C_suvix_frames", extractor_factory=make_factory(EXPECTED)
        )
        assert result.error is None
        assert result.result is not None
        assert result.result.execution.strategy == "selected_frames"
        # C is single-pass: refinement is baseline D's variable, not C's.
        assert result.result.execution.refinement_rounds == 0
        assert result.result.usage.provider_requests == 1
        assert result.result.usage.sampled_frames > 0
        assert result.metrics["event_f1"] == pytest.approx(1.0)
        assert result.metrics["schema_pass"] == pytest.approx(1.0)

    async def test_d_coarse_to_fine_runs_bounded_refinement(self, long_clip_path):
        # Milestones 5/8: baseline D runs the real coarse-to-fine workflow.
        script = [
            {"data": {"candidate_intervals": [
                {"start_seconds": 0.0, "end_seconds": 10.0, "reason": "flash"}
            ]}},
            {"data": EXPECTED},
        ]

        def factory(baseline: str) -> VideoExtractor:
            return FakeExtractor(script=script)

        task = make_task(str(long_clip_path))
        result = await run_baseline(
            task, "D_suvix_coarse_to_fine", extractor_factory=factory
        )
        assert result.error is None
        assert result.result is not None
        assert result.result.execution.strategy == "selected_frames"
        assert result.result.execution.refinement_rounds == 1
        assert result.result.usage.provider_requests == 2
        assert result.metrics["event_f1"] == pytest.approx(1.0)

    async def test_e_direct_frames_submits_locally_sampled_frames(
        self, long_clip_path
    ):
        # Milestone 8: baseline E samples frames locally and calls the adapter
        # directly, bypassing orchestration.
        extractor = FakeExtractor(script=[{"data": EXPECTED}])

        def factory(baseline: str) -> VideoExtractor:
            return extractor

        task = make_task(str(long_clip_path))
        result = await run_baseline(
            task, "E_direct_frames", extractor_factory=factory
        )
        assert result.error is None
        assert result.result is not None
        assert result.result.execution.strategy == "direct_frames"
        assert result.result.execution.stages == [
            "sample_frames", "adapter_extract",
        ]
        # Exactly one adapter call, with real sampled frames attached.
        assert len(extractor.calls) == 1
        assert extractor.calls[0].strategy == "selected_frames"
        assert extractor.calls[0].frames
        assert all(f.image_bytes for f in extractor.calls[0].frames)
        assert result.result.usage.sampled_frames == len(
            extractor.calls[0].frames
        )
        assert result.metrics["event_f1"] == pytest.approx(1.0)

    async def test_e_skipped_honestly_without_image_input(self, long_clip_path):
        caps = ExtractorCapabilities(
            provider="fake", model="noimg", native_video=True, image_input=False
        )

        def factory(baseline: str) -> VideoExtractor:
            return FakeExtractor(script=[{"data": EXPECTED}], capabilities=caps)

        task = make_task(str(long_clip_path))
        result = await run_baseline(
            task, "E_direct_frames", extractor_factory=factory
        )
        assert result.result is None
        assert "not applicable" in result.error
        assert any("optional baseline" in n for n in result.comparability_notes)

    async def test_missing_video_file_is_an_error_not_a_crash(self, tmp_path):
        task = make_task(str(tmp_path / "does-not-exist.mp4"))
        result = await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(EXPECTED)
        )
        assert result.result is None
        assert "not found" in result.error

    async def test_unknown_baseline_rejected(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        with pytest.raises(ValueError, match="unknown baseline"):
            await run_baseline(task, "Z_nope", extractor_factory=make_factory(EXPECTED))


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


class TestOutputWriting:
    async def test_writes_only_when_output_dir_given(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        out = tmp_path / "out"
        result = await run_baseline(
            task,
            "B_suvix_native",
            extractor_factory=make_factory(EXPECTED),
            output_dir=out,
        )
        files = list(out.glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text())
        assert payload["task_id"] == "temporal_flashes"
        assert payload["baseline"] == "B_suvix_native"
        assert "run_id" in payload and "timestamp" in payload
        assert payload["metrics"]["event_f1"] == pytest.approx(1.0)
        assert "pricing" in payload  # source/date recorded, even when unavailable
        assert result.metrics  # in-memory metrics still returned

    async def test_no_output_dir_no_files(self, tmp_path, monkeypatch):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        monkeypatch.chdir(tmp_path)  # prove nothing is written to CWD either
        await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(EXPECTED)
        )
        assert list(tmp_path.glob("*.json")) == []
        assert list(tmp_path.glob("benchmark*")) == []


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


class TestSummarize:
    async def _two_results(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        r1 = await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(EXPECTED)
        )
        predicted = {"events": [{"type": "flash", "timestamp_seconds": 2.5}]}
        r2 = await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(predicted)
        )
        return [r1, r2]

    async def test_per_baseline_table_no_single_score(self, tmp_path):
        results = await self._two_results(tmp_path)
        summary = summarize(results)
        assert set(summary) == {"B_suvix_native"}
        table = summary["B_suvix_native"]
        assert table["n_tasks"] == 2
        assert table["n_failed"] == 0
        assert table["failure_rate"] == pytest.approx(0.0)
        # Per-metric means stay separate — no collapsed score.
        assert "score" not in table
        assert "total_score" not in table
        means = table["metric_means"]
        assert means["event_f1"]["mean"] == pytest.approx((1.0 + 2 / 3) / 2)
        assert means["event_f1"]["n"] == 2
        assert means["event_recall"]["mean"] == pytest.approx((1.0 + 0.5) / 2)

    async def test_failures_counted(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        task = make_task(str(video))
        ok = await run_baseline(
            task, "B_suvix_native", extractor_factory=make_factory(EXPECTED)
        )
        failed = await run_baseline(
            task, "C_suvix_frames", extractor_factory=make_factory(EXPECTED)
        )
        summary = summarize([ok, failed])
        assert summary["C_suvix_frames"]["n_failed"] == 1
        assert summary["C_suvix_frames"]["failure_rate"] == pytest.approx(1.0)
        assert summary["B_suvix_native"]["failure_rate"] == pytest.approx(0.0)
