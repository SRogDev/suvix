"""Core extraction pipeline (Milestone 1).

Steps: normalize request → validate inputs and schema → inspect adapter
capabilities → select strategy → provider extraction → normalize output →
validate output (+ evidence sanity) → bounded recovery → assemble result.

The ``selected_frames`` branch is intentionally unimplemented here: it needs
the media layer (Milestone 2) and the coarse-to-fine workflow (Milestone 5).
Requesting it raises a documented :class:`UnsupportedStrategyError` rather
than silently doing something else.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from suvix.adapters.base import AdapterRequest, ProviderExtraction, VideoExtractor
from suvix.contracts import (
    ExecutionMetadata,
    ExtractionResult,
    ValidationIssue,
    ValidationReport,
)
from suvix.errors import (
    InvalidInputError,
    MalformedOutputError,
    ProviderRequestError,
    ProviderTimeoutError,
    RecoveryExhaustedError,
    SchemaValidationError,
    SuvixError,
    UnsupportedStrategyError,
)
from suvix.evidence import validate_evidence_timestamps
from suvix.options import ExtractionOptions
from suvix.planner import StrategyDecision, select_strategy
from suvix.recovery import build_repair_request, is_recoverable
from suvix.usage import build_usage
from suvix.validation import validate_data, validate_schema

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
    extraction: ProviderExtraction, schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, ValidationReport]:
    """Normalize + validate one provider outcome.

    Malformed output becomes a report issue (code ``malformed_output``) instead
    of raising immediately, so bounded recovery gets a chance to repair it.
    """
    try:
        data = _normalize_output(extraction)
    except MalformedOutputError as exc:
        return None, ValidationReport(
            valid=False,
            issues=[ValidationIssue(code="malformed_output", message=str(exc))],
        )
    return data, _combine_reports(
        validate_data(data, schema),
        validate_evidence_timestamps(extraction.evidence),
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


def _combine_reports(
    data_report: ValidationReport, evidence_issues: list[ValidationIssue]
) -> ValidationReport:
    if not evidence_issues:
        return data_report
    return ValidationReport(
        valid=data_report.valid and not evidence_issues,
        issues=[*data_report.issues, *evidence_issues],
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
        raise UnsupportedStrategyError(
            "Strategy 'selected_frames' is not implemented yet (Milestone 5: "
            "selected-frame extraction + coarse-to-fine workflow). Use "
            "'native_video' with an adapter that supports it, or wait for M5. "
            "Suvix will not silently fall back to another strategy.",
            details={"strategy": "selected_frames"},
        )

    stages = ["validate_inputs", "select_strategy", "adapter_extract"]
    provider_calls = 0
    recovery_attempts = 0

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
    provider_calls += 1

    # 5-7. Normalize output, validate structurally + evidence sanity.
    # Malformed output becomes a recoverable report issue, not an instant raise.
    data, report = _validate_extraction(extraction, schema)

    # 8. Bounded selective recovery (same extractor, same model, same strategy).
    budget = options.max_recovery_attempts if options.enable_recovery else 0
    while not report.valid and is_recoverable(data, report) and recovery_attempts < budget:
        recovery_attempts += 1
        stages.append(f"recovery_attempt_{recovery_attempts}")
        repair_request = build_repair_request(request, report)
        extraction = await _call_adapter(
            extractor, repair_request, options.per_call_timeout_seconds
        )
        provider_calls += 1
        data, report = _validate_extraction(extraction, schema)

    # 9. Final verdict: raise documented errors, never silent empty data.
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
    usage = build_usage(
        provider_usage=extraction.usage if options.collect_usage else {},
        provider_requests=provider_calls,
        recovery_requests=recovery_attempts,
        started_at=started_at,
    )
    execution = ExecutionMetadata(
        strategy=decision.strategy,
        strategy_reason=decision.reason,
        provider=capabilities.provider,
        model=capabilities.model,
        stages=stages,
        recovery_attempts=recovery_attempts,
        validation_status="passed",
        warnings=list(extraction.warnings),
        elapsed_seconds=max(time.perf_counter() - started_at, 0.0),
        provider_calls=provider_calls,
    )
    return ExtractionResult(
        data=data,
        evidence=list(extraction.evidence),
        validation=report,
        usage=usage,
        execution=execution,
    )
