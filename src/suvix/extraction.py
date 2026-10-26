"""Core extraction pipeline (Milestones 1 + 5).

Steps: normalize request → validate inputs and schema → inspect adapter
capabilities → select strategy → provider extraction → normalize output →
validate output (+ evidence sanity) → bounded recovery → assemble result.

The ``selected_frames`` branch (Milestone 5): inspect media, sample a bounded
set of frames uniformly, send them to the adapter, then run the same
normalize → validate → bounded recovery flow as the native branch. When
``options.max_refinement_rounds > 0`` the extraction step is delegated to
the bounded coarse-to-fine workflow in :mod:`suvix.sampling.coarse_to_fine`.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    FrameInput,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.contracts import (
    ExecutionMetadata,
    ExtractionResult,
    ValidationIssue,
    ValidationReport,
)
from suvix.errors import (
    InvalidInputError,
    MalformedOutputError,
    MediaProcessingError,
    MissingEvidenceError,
    ProviderRequestError,
    ProviderTimeoutError,
    RecoveryExhaustedError,
    SchemaValidationError,
    SuvixError,
    UnsupportedMediaError,
)
from suvix.evidence import validate_evidence, validate_evidence_timestamps
from suvix.media.frames import FrameRegistry, SampledFrame, extract_frames_at
from suvix.media.metadata import inspect_video
from suvix.options import ExtractionOptions
from suvix.planner import StrategyDecision, select_strategy
from suvix.recovery import build_repair_request, is_recoverable
from suvix.sampling.uniform import uniform_timestamps
from suvix.usage import build_usage
from suvix.validation import (
    SemanticContext,
    validate_data,
    validate_schema,
    validate_semantics,
)

_FENCE_PREFIXES = ("```json", "```")


def _normalize_video(video: Any) -> str:
    if isinstance(video, (str, os.PathLike)):
        path = os.fspath(video)
        if path.strip():
            return path
    raise InvalidInputError(
        f"video must be a non-empty local file path, got {type(video).__name__}.",
        details={"received_type": type(video).__name__},
    )


def _parse_provider_text(raw_text: str) -> dict[str, Any]:
    """Parse provider text output, tolerating markdown fences. Never invents data."""
    text = raw_text.strip()
    for fence in _FENCE_PREFIXES:
        if text.startswith(fence):
            text = text[len(fence):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedOutputError(
            "Provider returned text that is not valid JSON and no parsed "
            f"data was provided: {exc.msg}",
            details={"json_error": exc.msg, "position": exc.pos},
        ) from exc
    if not isinstance(parsed, dict):
        raise MalformedOutputError(
            "Provider output parsed as JSON but is not an object; "
            "suvix requires a JSON object matching the schema.",
            details={"parsed_type": type(parsed).__name__},
        )
    return parsed


def _normalize_output(extraction: ProviderExtraction) -> dict[str, Any]:
    if extraction.data is not None:
        if not isinstance(extraction.data, dict):
            raise MalformedOutputError(
                "Adapter returned non-object data.",
                details={"data_type": type(extraction.data).__name__},
            )
        return extraction.data
    if extraction.raw_text:
        return _parse_provider_text(extraction.raw_text)
    raise MalformedOutputError(
        "Adapter returned neither parsed data nor text output.",
        details={},
    )


def _validate_extraction(
    extraction: ProviderExtraction,
    schema: dict[str, Any],
    *,
    context: SemanticContext | None = None,
) -> tuple[dict[str, Any] | None, ValidationReport]:
    """Normalize + validate one provider outcome.

    Malformed output becomes a report issue (code ``malformed_output``) instead
    of raising immediately, so bounded recovery gets a chance to repair it.

    Beyond structural validation, deterministic semantic checks always run
    (finite, non-negative, ordered time values). When ``context`` carries
    media knowledge (video duration, frame registry), the full evidence
    validation runs too: timestamps must fall within the duration (+ tolerance)
    and ``frame`` evidence must resolve in the registry.
    """
    try:
        data = _normalize_output(extraction)
    except MalformedOutputError as exc:
        return None, ValidationReport(
            valid=False,
            issues=[ValidationIssue(code="malformed_output", message=str(exc))],
        )
    ctx = context if context is not None else SemanticContext()
    issues = list(validate_data(data, schema).issues)
    if ctx.video_duration_seconds is not None or ctx.frame_registry is not None:
        issues.extend(
            validate_evidence(
                list(extraction.evidence),
                video_duration_seconds=ctx.video_duration_seconds,
                frame_registry=ctx.frame_registry,
                tolerance_seconds=ctx.timestamp_tolerance_seconds,
            )
        )
    else:
        issues.extend(validate_evidence_timestamps(extraction.evidence))
    issues.extend(validate_semantics(data, context=ctx))
    return data, ValidationReport(
        valid=not any(issue.severity == "error" for issue in issues),
        issues=issues,
    )


async def _call_adapter(
    extractor: VideoExtractor,
    request: AdapterRequest,
    timeout: float | None,
) -> ProviderExtraction:
    try:
        if timeout is not None:
            return await asyncio.wait_for(extractor.extract(request), timeout)
        return await extractor.extract(request)
    except asyncio.CancelledError:
        # Preserve cancellation semantics: never convert into an empty result.
        raise
    except (ProviderRequestError, SuvixError):
        raise
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise ProviderTimeoutError(
            f"Provider call timed out after {timeout}s.",
            details={"timeout_seconds": timeout},
        ) from exc
    except Exception as exc:  # adapter bug or unexpected SDK failure
        raise ProviderRequestError(
            f"Adapter {extractor.name} failed: {exc}",
            details={"adapter": extractor.name, "error_type": type(exc).__name__},
        ) from exc


def _to_frame_input(frame: SampledFrame) -> FrameInput:
    return FrameInput(
        frame_id=frame.frame_id,
        timestamp_seconds=frame.timestamp_seconds,
        image_bytes=frame.image_bytes,
        mime_type=frame.mime_type,
    )


def _filter_unknown_frame_evidence(
    extraction: ProviderExtraction, registry: FrameRegistry
) -> tuple[ProviderExtraction, list[str]]:
    """Drop evidence referencing frame ids Suvix never sampled.

    A provider can only honestly reference frames it was actually sent.
    Unknown ids are dropped (never fabricated, never passed through) and
    each drop is reported as a warning naming the id.
    """
    kept: list[Any] = []
    dropped_warnings: list[str] = []
    for ref in extraction.evidence:
        if ref.frame_id is not None and registry.lookup(ref.frame_id) is None:
            dropped_warnings.append(
                f"provider referenced unknown frame_id '{ref.frame_id}'"
            )
            continue
        kept.append(ref)
    if not dropped_warnings:
        return extraction, []
    return (
        ProviderExtraction(
            data=extraction.data,
            raw_text=extraction.raw_text,
            evidence=kept,
            usage=extraction.usage,
            warnings=list(extraction.warnings),
        ),
        dropped_warnings,
    )


async def _finalize(
    *,
    extraction: ProviderExtraction,
    request: AdapterRequest,
    schema: dict[str, Any],
    options: ExtractionOptions,
    decision: StrategyDecision,
    capabilities: ExtractorCapabilities,
    extractor: VideoExtractor,
    started_at: float,
    stages: list[str],
    provider_calls: int,
    frame_count: int,
    sampled_frames: int,
    video_duration_seconds: float | None,
    refinement_rounds: int,
    registry: FrameRegistry | None,
) -> ExtractionResult:
    """Shared tail: evidence honesty → normalize/validate → bounded recovery → result.

    ``registry`` is ``None`` for the native-video branch (no local frames, so
    no frame-id check applies); the selected-frames branch passes its registry
    so provider-referenced frame ids are validated on every provider outcome,
    including repair attempts.
    """
    dropped_warnings: list[str] = []
    if registry is not None:
        extraction, dropped = _filter_unknown_frame_evidence(extraction, registry)
        dropped_warnings.extend(dropped)

    # Normalize output, then validate: structural + deterministic semantic
    # checks, with full evidence validation when media context is known.
    # Malformed output becomes a recoverable report issue, not an instant raise.
    context = SemanticContext(
        video_duration_seconds=video_duration_seconds,
        frame_registry=registry,
    )
    data, report = _validate_extraction(extraction, schema, context=context)

    # Bounded selective recovery (same extractor, same model, same strategy).
    recovery_attempts = 0
    budget = options.max_recovery_attempts if options.enable_recovery else 0
    while not report.valid and is_recoverable(data, report) and recovery_attempts < budget:
        recovery_attempts += 1
        stages.append(f"recovery_attempt_{recovery_attempts}")
        repair_request = build_repair_request(request, report)
        extraction = await _call_adapter(
            extractor, repair_request, options.per_call_timeout_seconds
        )
        provider_calls += 1
        if registry is not None:
            extraction, dropped = _filter_unknown_frame_evidence(extraction, registry)
            dropped_warnings.extend(dropped)
        data, report = _validate_extraction(extraction, schema, context=context)

    # Final verdict: raise documented errors, never silent empty data.
    if not report.valid:
        details = {
            "issues": [i.model_dump() for i in report.issues],
            "recovery_attempts": recovery_attempts,
        }
        if recovery_attempts > 0:
            raise RecoveryExhaustedError(
                f"Recovery budget exhausted ({recovery_attempts} attempts) "
                "without producing schema-valid output.",
                details=details,
            )
        if data is None:
            malformed = next(
                (i.message for i in report.issues if i.code == "malformed_output"),
                "provider output was not parseable",
            )
            raise MalformedOutputError(malformed, details=details)
        raise SchemaValidationError(
            "Extracted data failed local JSON Schema validation.",
            details=details,
        )

    assert data is not None  # valid report implies parseable object output
    if options.require_evidence and not extraction.evidence:
        raise MissingEvidenceError(
            "options.require_evidence=True but the extraction produced no "
            "evidence references.",
            details={"strategy": decision.strategy,
                     "provider": capabilities.provider},
        )
    usage = build_usage(
        provider_usage=extraction.usage if options.collect_usage else {},
        provider_requests=provider_calls,
        recovery_requests=recovery_attempts,
        sampled_frames=sampled_frames,
        video_duration_seconds=video_duration_seconds,
        started_at=started_at,
    )
    execution = ExecutionMetadata(
        strategy=decision.strategy,
        strategy_reason=decision.reason,
        provider=capabilities.provider,
        model=capabilities.model,
        stages=stages,
        refinement_rounds=refinement_rounds,
        recovery_attempts=recovery_attempts,
        validation_status="passed",
        warnings=[*dropped_warnings, *extraction.warnings],
        elapsed_seconds=max(time.perf_counter() - started_at, 0.0),
        frame_count=frame_count,
        provider_calls=provider_calls,
    )
    return ExtractionResult(
        data=data,
        evidence=list(extraction.evidence),
        validation=report,
        usage=usage,
        execution=execution,
    )


async def _run_selected_frames(
    *,
    video_path: str,
    schema: dict[str, Any],
    instructions: str,
    extractor: VideoExtractor,
    options: ExtractionOptions,
    decision: StrategyDecision,
    capabilities: ExtractorCapabilities,
    started_at: float,
) -> ExtractionResult:
    """Selected-frames pipeline: inspect media → sample → extract → validate.

    Evidence honesty note: sampled frames are deliberately NOT auto-attached
    as evidence — that would claim every sampled frame supports the result.
    Provider evidence is kept as-is after frame-id validation against the
    local registry; the registry itself holds the verified
    ``frame_id → timestamp`` references for the benchmark layer.
    """
    stages = ["validate_inputs", "select_strategy", "inspect_media"]

    # 1. Inspect media (bounded by the developer's limits).
    metadata = await inspect_video(
        video_path,
        max_file_bytes=options.max_file_bytes,
        max_duration_seconds=options.max_duration_seconds,
    )
    duration = metadata.duration_seconds
    if duration is None:
        raise UnsupportedMediaError(
            "Cannot run the selected-frames strategy: the video duration is "
            "unknown, so no sampling plan can be built.",
            details={"video_path": video_path},
        )

    # 2. Bounded sampling plan: uniform, or scene-change candidates merged
    # with a uniform floor when the planner flagged scene sampling.
    refine = options.max_refinement_rounds > 0
    coarse_budget = options.max_frames
    if refine:
        # Reserve roughly half the frame budget for fine rounds so the total
        # sampled across coarse + fine rounds never exceeds max_frames.
        coarse_budget = min(options.max_frames, max(2, options.max_frames // 2))
    if decision.requires_scene_sampling:
        from suvix.sampling.scene_changes import make_scene_sampler

        scene_sampler = make_scene_sampler(
            video_path,
            threshold=options.scene_threshold,
            floor_fraction=options.scene_floor_fraction,
        )
        timestamps = await asyncio.to_thread(
            scene_sampler, duration_seconds=duration, max_frames=coarse_budget
        )
    else:
        timestamps = uniform_timestamps(
            duration_seconds=duration,
            max_frames=coarse_budget,
            interval_seconds=options.coarse_interval_seconds,
        )
    if not timestamps:
        raise MediaProcessingError(
            "Sampling produced no timestamps for "
            f"duration_seconds={duration!r}.",
            details={"duration_seconds": duration},
        )
    if len(timestamps) > options.max_frames:
        raise MediaProcessingError(
            "Sampling plan exceeds the frame budget: "
            f"{len(timestamps)} timestamps > max_frames={options.max_frames}.",
            details={
                "planned_timestamps": len(timestamps),
                "max_frames": options.max_frames,
            },
        )

    # 3. Extract the sampled frames (registered for evidence verification).
    stages.append("sample_frames")
    registry = FrameRegistry()
    coarse_frames = await extract_frames_at(
        video_path, timestamps, max_frames=coarse_budget, registry=registry
    )
    if not coarse_frames:
        raise MediaProcessingError(
            "Frame extraction returned no frames for the sampled timestamps.",
            details={"planned_timestamps": len(timestamps)},
        )

    # 4. Provider extraction: bounded coarse-to-fine, or a single pass.
    if refine:
        from suvix.sampling.coarse_to_fine import coarse_to_fine_extract

        outcome = await coarse_to_fine_extract(
            video_path=video_path,
            metadata=metadata,
            options=options,
            extractor=extractor,
            schema=schema,
            instructions=instructions,
            coarse_frames=coarse_frames,
            registry=registry,
        )
        stages.append("coarse_pass")
        stages.extend(f"refine_round_{i + 1}" for i in range(outcome.rounds_used))
        return await _finalize(
            extraction=outcome.extraction,
            request=outcome.last_request,
            schema=schema,
            options=options,
            decision=decision,
            capabilities=capabilities,
            extractor=extractor,
            started_at=started_at,
            stages=stages,
            provider_calls=1 + outcome.rounds_used,
            frame_count=outcome.total_frames,
            sampled_frames=outcome.total_frames,
            video_duration_seconds=duration,
            refinement_rounds=outcome.rounds_used,
            registry=registry,
        )

    request = AdapterRequest(
        video_path=video_path,
        schema=schema,
        instructions=instructions,
        options=options,
        frames=[_to_frame_input(frame) for frame in coarse_frames],
        strategy="selected_frames",
    )
    stages.append("adapter_extract")
    extraction = await _call_adapter(
        extractor, request, options.per_call_timeout_seconds
    )
    return await _finalize(
        extraction=extraction,
        request=request,
        schema=schema,
        options=options,
        decision=decision,
        capabilities=capabilities,
        extractor=extractor,
        started_at=started_at,
        stages=stages,
        provider_calls=1,
        frame_count=len(coarse_frames),
        sampled_frames=len(coarse_frames),
        video_duration_seconds=duration,
        refinement_rounds=0,
        registry=registry,
    )


async def run_extraction(
    *,
    video: Any,
    schema: dict[str, Any],
    instructions: str,
    extractor: VideoExtractor,
    options: ExtractionOptions | None = None,
) -> ExtractionResult:
    """Execute the full extraction pipeline for one request."""
    started_at = time.perf_counter()
    options = options or ExtractionOptions()

    # 1-2. Normalize and validate inputs before touching any provider.
    video_path = _normalize_video(video)
    if not isinstance(instructions, str) or not instructions.strip():
        raise InvalidInputError("instructions must be a non-empty string.")
    validate_schema(schema)

    # 3-4. Capabilities + strategy selection (recorded, never hidden).
    capabilities = extractor.capabilities
    decision: StrategyDecision = select_strategy(
        capabilities=capabilities, options=options
    )
    if decision.strategy == "selected_frames":
        return await _run_selected_frames(
            video_path=video_path,
            schema=schema,
            instructions=instructions,
            extractor=extractor,
            options=options,
            decision=decision,
            capabilities=capabilities,
            started_at=started_at,
        )

    stages = ["validate_inputs", "select_strategy", "adapter_extract"]

    request = AdapterRequest(
        video_path=video_path,
        schema=schema,
        instructions=instructions,
        options=options,
        strategy=decision.strategy,
    )
    extraction = await _call_adapter(
        extractor, request, options.per_call_timeout_seconds
    )

    return await _finalize(
        extraction=extraction,
        request=request,
        schema=schema,
        options=options,
        decision=decision,
        capabilities=capabilities,
        extractor=extractor,
        started_at=started_at,
        stages=stages,
        provider_calls=1,
        frame_count=0,
        sampled_frames=0,
        video_duration_seconds=None,
        refinement_rounds=0,
        registry=None,
    )
