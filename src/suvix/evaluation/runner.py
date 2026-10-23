"""Benchmark runner: baselines A–E from SUVIX_PLAN.md §16.2.

Baselines:

- ``A_direct_native``: direct adapter ``extract()`` call with the video, the
  task schema, and the instructions — bypassing Suvix orchestration (no
  strategy selection, recovery, or usage aggregation). Measures raw provider
  capability. Suvix validation is applied locally *for measurement only*;
  the result's ``execution.stages`` records exactly what ran.
- ``B_suvix_native``: ``Suvix().extract`` with ``strategy="native_video"``.
- ``C_suvix_frames``: ``Suvix().extract`` with ``strategy="selected_frames"``
  (local frame sampling + single-pass extraction through the adapter).
- ``D_suvix_coarse_to_fine``: ``Suvix().extract`` with
  ``strategy="selected_frames"`` and ``max_refinement_rounds=2`` (bounded
  coarse-to-fine workflow).
- ``E_direct_frames``: direct adapter ``extract()`` call with locally sampled
  frames (the same uniform plan baseline C uses) — bypassing Suvix
  orchestration. Only meaningful for adapters with image input.

Fair-comparison guardrails (§16.3): the same schema, instructions, and video
are used for every baseline; the provider/model are recorded per run; every
unavoidable difference lands in ``comparability_notes``. Nothing is
silently substituted.

Results are written to disk ONLY when ``output_dir`` is explicitly provided
(§16.6 — no automatic persistent benchmark history in the library).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from suvix.adapters.base import (
    AdapterRequest,
    FrameInput,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.api import Suvix
from suvix.contracts import (
    EvidenceRef,
    ExecutionMetadata,
    ExtractionResult,
    ValidationIssue,
    ValidationReport,
)
from suvix.evaluation import metrics
from suvix.evaluation.cost import resolve_pricing
from suvix.media.frames import FrameRegistry, extract_frames_at
from suvix.media.metadata import inspect_video
from suvix.options import ExtractionOptions
from suvix.sampling.uniform import uniform_timestamps
from suvix.usage import build_usage
from suvix.validation import validate_data

BASELINES: tuple[str, ...] = (
    "A_direct_native",
    "B_suvix_native",
    "C_suvix_frames",
    "D_suvix_coarse_to_fine",
    "E_direct_frames",
)

BaselineName = Literal[
    "A_direct_native",
    "B_suvix_native",
    "C_suvix_frames",
    "D_suvix_coarse_to_fine",
    "E_direct_frames",
]

TaskCategory = Literal["temporal_events", "objects_counts", "visible_text"]

ExtractorFactory = Callable[[str], VideoExtractor]
"""Build an extractor for a baseline name. Called once per ``run_baseline``."""


class BenchmarkTask(BaseModel):
    """One hand-annotated benchmark case (§16.5).

    Either ``video_path`` (a bundled local video) or ``video_ref`` plus
    ``video_sha256`` (a documented external reference) must be given.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    category: TaskCategory
    video_path: str | None = None
    video_ref: str | None = None
    video_sha256: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    instructions: str
    expected: dict[str, Any]
    time_tolerance_seconds: float = Field(default=1.0, gt=0)
    evaluation_notes: str = ""
    known_ambiguities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _video_reference(self) -> BenchmarkTask:
        if self.video_path is None:
            if self.video_ref is None or self.video_sha256 is None:
                raise ValueError(
                    "either video_path or both video_ref and video_sha256 "
                    "must be provided"
                )
        return self


class BaselineResult(BaseModel):
    """Outcome of one baseline on one task.

    ``metrics`` holds per-dimension metric values (see
    :mod:`suvix.evaluation.metrics`); ``comparability_notes`` records every
    unavoidable difference from a perfectly fair comparison (§16.3).
    """

    model_config = ConfigDict(extra="forbid")

    baseline: str
    task_id: str
    result: ExtractionResult | None = None
    error: str | None = None
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    comparability_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _structural_metrics(result: ExtractionResult) -> dict[str, float | int | None]:
    issues = result.validation.issues
    missing_required = any("is a required property" in i.message for i in issues)
    invalid_evidence = any(
        (e.ref_type == "frame" and not e.frame_id)
        or (
            e.ref_type == "segment"
            and (e.start_seconds is None or e.end_seconds is None)
        )
        for e in result.evidence
    )
    return {
        "json_parse_success": 1.0,  # a returned result implies parseable output
        "schema_pass": 1.0 if result.validation.valid else 0.0,
        "missing_required_field": 1.0 if missing_required else 0.0,
        "invalid_evidence": 1.0 if invalid_evidence else 0.0,
    }


def _semantic_metrics(task: BenchmarkTask, data: dict[str, Any]) -> dict[str, Any]:
    tol = task.time_tolerance_seconds
    out: dict[str, Any] = {}
    if task.category == "temporal_events":
        predicted = data.get("events", [])
        expected = task.expected.get("events", [])
        if not isinstance(predicted, list):
            predicted = []
        prf = metrics.event_precision_recall_f1(
            predicted, expected, time_tolerance_s=tol
        )
        out["event_precision"] = prf["precision"]
        out["event_recall"] = prf["recall"]
        out["event_f1"] = prf["f1"]
        out["duplicate_event_rate"] = metrics.duplicate_event_rate(
            predicted, expected, time_tolerance_s=tol
        )
        out["unsupported_claim_rate"] = metrics.unsupported_claim_rate(
            predicted, expected, time_tolerance_s=tol
        )
        pred_times = [
            e["timestamp_seconds"]
            for e in predicted
            if isinstance(e, dict)
            and isinstance(e.get("timestamp_seconds"), (int, float))
        ]
        exp_times = [
            e["timestamp_seconds"]
            for e in expected
            if isinstance(e, dict)
            and isinstance(e.get("timestamp_seconds"), (int, float))
        ]
        out["timestamp_mae"] = metrics.timestamp_mae(
            pred_times, exp_times, time_tolerance_s=tol
        )
        n_pred = len(predicted) if predicted else 0
        out["n_correct_events"] = (
            round(prf["precision"] * n_pred) if prf["precision"] is not None else 0
        )
    elif task.category == "objects_counts":
        expected_counts = task.expected.get("counts", {})
        predicted_counts = data.get("counts", {})
        if not isinstance(predicted_counts, dict):
            predicted_counts = {}
        per_label = [
            metrics.count_accuracy(predicted_counts.get(label), count)
            for label, count in expected_counts.items()
        ]
        out["count_accuracy_mean"] = (
            sum(per_label) / len(per_label) if per_label else None
        )
        out["count_labels_exact"] = sum(1 for v in per_label if v == 1.0)
        out["count_labels_total"] = len(per_label)
        out["n_correct_events"] = out["count_labels_exact"]
    elif task.category == "visible_text":
        expected_texts = task.expected.get("texts", {})
        per_field = []
        for field, expected_text in expected_texts.items():
            predicted_text = data.get(field)
            per_field.append(
                metrics.text_exact_accuracy(
                    str(predicted_text) if predicted_text is not None else "",
                    str(expected_text),
                )
            )
        out["text_accuracy_mean"] = (
            sum(per_field) / len(per_field) if per_field else None
        )
        out["n_correct_events"] = sum(1 for v in per_field if v == 1.0)
    return out


def _compute_metrics(task: BenchmarkTask, result: ExtractionResult) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out.update(_structural_metrics(result))
    out.update(_semantic_metrics(task, result.data))
    usage = result.usage
    out["latency_seconds"] = usage.latency_seconds
    out["provider_requests"] = usage.provider_requests
    out["recovery_requests"] = usage.recovery_requests
    out["sampled_frames"] = usage.sampled_frames
    # No pricing table is bundled (see suvix.evaluation.cost), so without a
    # user-supplied table every economic figure stays unavailable — by design.
    out["estimated_cost_usd"] = usage.estimated_cost_usd
    out["cost_per_correct_event"] = metrics.cost_per_correct_event(
        usage.estimated_cost_usd, int(out.get("n_correct_events") or 0)
    )
    return out


# ---------------------------------------------------------------------------
# Baseline implementations
# ---------------------------------------------------------------------------


def _common_notes(task: BenchmarkTask, baseline: str) -> list[str]:
    return [
        f"Baseline {baseline}: same schema, instructions, and video "
        f"({task.video_path or task.video_ref}) as every other baseline; "
        "differences below are the only allowed deviations (§16.3).",
    ]


def _resolve_video(task: BenchmarkTask) -> tuple[str | None, str | None]:
    """Return (video_path, error). video_path may be None for external refs."""
    if task.video_path is not None:
        if not os.path.exists(task.video_path):
            return None, f"video file not found: {task.video_path}"
        return task.video_path, None
    return None, None  # external video_ref: the adapter resolves it


async def _run_a(
    task: BenchmarkTask, extractor_factory: ExtractorFactory
) -> tuple[ExtractionResult | None, str | None, list[str]]:
    notes = _common_notes(task, "A_direct_native")
    notes.append(
        "Baseline A calls the adapter's extract() directly, bypassing Suvix "
        "orchestration (no strategy selection, no recovery, no usage "
        "aggregation). It measures raw provider capability. Local schema "
        "validation is applied for measurement only."
    )
    video, error = _resolve_video(task)
    if error:
        return None, error, notes
    extractor = extractor_factory("A_direct_native")
    capabilities = extractor.capabilities
    if not capabilities.native_video:
        notes.append(
            "Adapter reports native_video=False: the direct call still submits "
            "the video path, but the provider may not support native video — "
            "results are not comparable to native-video baselines."
        )
    started = time.perf_counter()
    try:
        request = AdapterRequest(
            video_path=video,
            schema=task.schema_,
            instructions=task.instructions,
            options=ExtractionOptions(strategy="native_video"),
            strategy="native_video",
        )
        extraction = await extractor.extract(request)
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        return None, f"{type(exc).__name__}: {exc}", notes
    return _wrap_direct_extraction(
        task=task,
        baseline="A_direct_native",
        extractor=extractor,
        extraction=extraction,
        started=started,
        strategy="direct_native",
        strategy_reason=(
            "Baseline A: direct adapter call, bypassing Suvix orchestration."
        ),
        stages=["adapter_extract"],
        frame_count=0,
        sampled_frames=0,
        notes=notes,
    )


async def _run_e(
    task: BenchmarkTask, extractor_factory: ExtractorFactory
) -> tuple[ExtractionResult | None, str | None, list[str]]:
    """Baseline E: local frame sampling + direct adapter call.

    Uses Suvix's own media layer (the same uniform sampling plan baseline C
    uses) to select frames, then calls the adapter's ``extract()`` directly
    with those frames — bypassing orchestration (no strategy selection,
    recovery, or usage aggregation). Local schema validation is applied for
    measurement only. Adapters without image input are recorded as skipped,
    not scored (§16.2: optional baseline).
    """
    notes = _common_notes(task, "E_direct_frames")
    notes.append(
        "Baseline E submits locally sampled frames directly to the adapter, "
        "bypassing Suvix orchestration. It is the image-input mirror of "
        "baseline A (§16.2)."
    )
    video, error = _resolve_video(task)
    if error:
        return None, error, notes
    if video is None:
        # Baseline E samples frames from a local file; an external
        # video_ref has no local path to sample (previously this fell
        # through to inspect_video(None) and surfaced a raw TypeError).
        return (
            None,
            "Baseline E requires a local video_path: an external "
            "video_ref cannot be sampled locally.",
            notes,
        )
    extractor = extractor_factory("E_direct_frames")
    capabilities = extractor.capabilities
    if not (capabilities.image_input or capabilities.multi_image):
        reason = (
            "Adapter does not accept image input: baseline E is not "
            "applicable — skipped, not scored (§16.2: optional baseline)."
        )
        notes.append(reason)
        return None, reason, notes
    options = ExtractionOptions(strategy="selected_frames")
    try:
        metadata = await inspect_video(video)
        duration = metadata.duration_seconds
        if duration is None:
            return None, "video duration unknown; no sampling plan possible", notes
        timestamps = uniform_timestamps(
            duration_seconds=duration,
            max_frames=options.max_frames,
            interval_seconds=options.coarse_interval_seconds,
        )
        if len(timestamps) > options.max_frames:
            return None, "sampling plan exceeded the frame budget", notes
        registry = FrameRegistry()
        frames = await extract_frames_at(
            video, timestamps, max_frames=options.max_frames, registry=registry
        )
        request = AdapterRequest(
            video_path=None,
            schema=task.schema_,
            instructions=task.instructions,
            options=options,
            frames=[
                FrameInput(
                    frame_id=frame.frame_id,
                    timestamp_seconds=frame.timestamp_seconds,
                    image_bytes=frame.image_bytes,
                    mime_type=frame.mime_type,
                )
                for frame in frames
            ],
            strategy="selected_frames",
        )
        started = time.perf_counter()
        extraction = await extractor.extract(request)
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        return None, f"{type(exc).__name__}: {exc}", notes
    return _wrap_direct_extraction(
        task=task,
        baseline="E_direct_frames",
        extractor=extractor,
        extraction=extraction,
        started=started,
        strategy="direct_frames",
        strategy_reason=(
            "Baseline E: direct adapter call with locally sampled frames, "
            "bypassing Suvix orchestration."
        ),
        stages=["sample_frames", "adapter_extract"],
        frame_count=len(frames),
        sampled_frames=len(frames),
        notes=notes,
    )


def _wrap_direct_extraction(
    *,
    task: BenchmarkTask,
    baseline: str,
    extractor: VideoExtractor,
    extraction: ProviderExtraction,
    started: float,
    strategy: str,
    strategy_reason: str,
    stages: list[str],
    frame_count: int,
    sampled_frames: int,
    notes: list[str],
) -> tuple[ExtractionResult | None, str | None, list[str]]:
    """Shared measurement tail for the direct baselines (A and E).

    Parses the adapter output, applies local schema validation for
    measurement only, and wraps everything in an :class:`ExtractionResult`.
    """
    if extraction.data is not None and isinstance(extraction.data, dict):
        data: dict[str, Any] | None = extraction.data
        parse_ok = True
    elif extraction.raw_text:
        try:
            parsed = json.loads(extraction.raw_text)
            data = parsed if isinstance(parsed, dict) else None
            parse_ok = data is not None
        except (json.JSONDecodeError, ValueError):
            data, parse_ok = None, False
    else:
        data, parse_ok = None, False
    if not parse_ok:
        return None, "direct adapter output was not a parseable JSON object", notes
    assert data is not None
    report = validate_data(data, task.schema_)
    evidence = list(extraction.evidence or [])
    evidence_issues = _evidence_issues(evidence)
    if evidence_issues:
        report = ValidationReport(
            valid=False, issues=[*report.issues, *evidence_issues]
        )
    capabilities = extractor.capabilities
    usage = build_usage(
        provider_usage=extraction.usage,
        provider_requests=1,
        recovery_requests=0,
        sampled_frames=sampled_frames,
        started_at=started,
    )
    elapsed = max(time.perf_counter() - started, 0.0)
    result = ExtractionResult(
        data=data,
        evidence=evidence,
        validation=report,
        usage=usage,
        execution=ExecutionMetadata(
            strategy=strategy,
            strategy_reason=strategy_reason,
            provider=capabilities.provider,
            model=capabilities.model,
            stages=stages,
            validation_status="passed" if report.valid else "failed",
            warnings=list(extraction.warnings or []),
            elapsed_seconds=elapsed,
            frame_count=frame_count,
            provider_calls=1,
        ),
    )
    return result, None, notes


def _evidence_issues(evidence: list[EvidenceRef]) -> list[ValidationIssue]:
    issues = []
    for ref in evidence:
        if ref.ref_type == "frame" and not ref.frame_id:
            issues.append(
                ValidationIssue(
                    code="invalid_evidence",
                    message="frame evidence ref is missing frame_id",
                )
            )
        if ref.ref_type == "segment" and (
            ref.start_seconds is None or ref.end_seconds is None
        ):
            issues.append(
                ValidationIssue(
                    code="invalid_evidence",
                    message="segment evidence ref is missing time bounds",
                )
            )
    return issues


async def _run_suvix(
    task: BenchmarkTask,
    baseline: str,
    strategy: str,
    extractor_factory: ExtractorFactory,
    options: ExtractionOptions | None = None,
) -> tuple[ExtractionResult | None, str | None, list[str]]:
    notes = _common_notes(task, baseline)
    video, error = _resolve_video(task)
    if error:
        return None, error, notes
    try:
        extractor = extractor_factory(baseline)
        result = await Suvix().extract(
            video=video,
            schema=task.schema_,
            instructions=task.instructions,
            extractor=extractor,
            options=options or ExtractionOptions(strategy=strategy),  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        return None, f"{type(exc).__name__}: {exc}", notes
    return result, None, notes


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def run_baseline(
    task: BenchmarkTask,
    baseline: str,
    *,
    extractor_factory: ExtractorFactory,
    output_dir: str | Path | None = None,
) -> BaselineResult:
    """Run one baseline on one task and score it.

    Args:
        task: the annotated benchmark case.
        baseline: one of :data:`BASELINES`.
        extractor_factory: builds the extractor for the baseline (lets tests
            inject scripted fakes and real runs inject real adapters).
        output_dir: when given, the per-run JSON report is written there
            (explicit benchmark operation, §16.6). When ``None``, nothing is
            written anywhere.

    Returns a :class:`BaselineResult`; baseline execution failures are
    recorded in ``error``, never raised, so a broken baseline cannot abort a
    whole benchmark sweep. (An unknown ``baseline`` name is a programming
    error and raises :class:`ValueError`.)
    """
    if baseline not in BASELINES:
        raise ValueError(f"unknown baseline {baseline!r}; expected one of {BASELINES}")

    if baseline == "A_direct_native":
        result, error, notes = await _run_a(task, extractor_factory)
    elif baseline == "B_suvix_native":
        result, error, notes = await _run_suvix(
            task, baseline, "native_video", extractor_factory
        )
    elif baseline == "C_suvix_frames":
        result, error, notes = await _run_suvix(
            task,
            baseline,
            "selected_frames",
            extractor_factory,
            # Single pass: refinement is baseline D's variable, not C's.
            options=ExtractionOptions(
                strategy="selected_frames", max_refinement_rounds=0
            ),
        )
    elif baseline == "D_suvix_coarse_to_fine":
        result, error, notes = await _run_suvix(
            task,
            baseline,
            "selected_frames",
            extractor_factory,
            options=ExtractionOptions(
                strategy="selected_frames", max_refinement_rounds=2
            ),
        )
    else:  # E_direct_frames
        result, error, notes = await _run_e(task, extractor_factory)

    metrics_dict: dict[str, Any] = {}
    if result is not None:
        metrics_dict = _compute_metrics(task, result)

    baseline_result = BaselineResult(
        baseline=baseline,
        task_id=task.task_id,
        result=result,
        error=error,
        metrics=metrics_dict,
        comparability_notes=notes,
    )
    if output_dir is not None:
        _write_report(baseline_result, task, Path(output_dir))
    return baseline_result


def _write_report(
    baseline_result: BaselineResult, task: BenchmarkTask, output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    provider = model = strategy = None
    pricing_source, pricing_date = "unavailable", "unverified"
    if baseline_result.result is not None:
        execution = baseline_result.result.execution
        provider, model, strategy = (
            execution.provider,
            execution.model,
            execution.strategy,
        )
        _, pricing_source, pricing_date = resolve_pricing(
            execution.provider, execution.model
        )
    payload = {
        "run_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline": baseline_result.baseline,
        "task_id": baseline_result.task_id,
        "provider": provider,
        "model": model,
        "strategy": strategy,
        "task": task.model_dump(by_alias=True),
        "result": (
            baseline_result.result.model_dump()
            if baseline_result.result is not None
            else None
        ),
        "error": baseline_result.error,
        "metrics": baseline_result.metrics,
        "comparability_notes": baseline_result.comparability_notes,
        "pricing": {
            "source": pricing_source,
            "date": pricing_date,
        },
    }
    path = output_dir / f"{baseline_result.baseline}__{baseline_result.task_id}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def summarize(results: list[BaselineResult]) -> dict[str, Any]:
    """Aggregate results into a per-baseline metric table.

    Deliberately NOT a single score: trade-offs stay visible (§16.1). For
    each baseline: task counts, failure rate, per-metric means over the runs
    where the metric is defined (``None`` values are excluded, not zeroed),
    and the union of comparability notes.
    """
    grouped: dict[str, list[BaselineResult]] = {}
    for result in results:
        grouped.setdefault(result.baseline, []).append(result)

    summary: dict[str, Any] = {}
    for baseline, group in grouped.items():
        failed = [r for r in group if r.result is None or r.error is not None]
        metric_means: dict[str, dict[str, Any]] = {}
        names: set[str] = set()
        for r in group:
            names.update(r.metrics.keys())
        for name in sorted(names):
            values: list[float] = []
            for r in group:
                value = r.metrics.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append(float(value))
            if values:
                metric_means[name] = {
                    "n": len(values),
                    "mean": sum(values) / len(values),
                }
        notes: list[str] = []
        for r in group:
            for note in r.comparability_notes:
                if note not in notes:
                    notes.append(note)
        summary[baseline] = {
            "n_tasks": len(group),
            "n_succeeded": len(group) - len(failed),
            "n_failed": len(failed),
            "failure_rate": metrics.failure_rate([r in failed for r in group]),
            "task_ids": [r.task_id for r in group],
            "metric_means": metric_means,
            "comparability_notes": notes,
        }
    return summary
