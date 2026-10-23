"""Local validation: JSON Schema checks run before any provider call
(schema validity) and after extraction (structural conformance).

Draft: 2020-12 via the ``jsonschema`` package. A provider's claim of
structured output never replaces this local validation.

Wiring contract (Milestone 6, for the integrator):

The pipeline should run structural validation first, then merge deterministic
semantic issues into the same report *before* the recovery loop::

    report = validate_data(data, schema)
    report.issues += validate_semantics(
        data,
        context=SemanticContext(
            video_duration_seconds=usage.video_duration_seconds,
            frame_registry=frame_registry,  # duck-typed: .lookup(frame_id) -> float | None
        ),
    )
    report.valid = not any(i.severity == "error" for i in report.issues)

Use ``suvix.evidence.validate_evidence(...)`` instead of
``validate_evidence_timestamps(...)`` once the duration and frame registry
are known. Reports with only warnings are not recoverable — see
``suvix.recovery.is_recoverable`` — so the recovery budget is never spent
on warnings.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict

from suvix.contracts import ValidationIssue, ValidationReport
from suvix.errors import UnsupportedSchemaError

SCHEMA_DRAFT = "2020-12"


class SemanticContext(BaseModel):
    """Media-derived context for deterministic semantic checks.

    ``frame_registry`` is duck-typed — it only needs
    ``.lookup(frame_id) -> float | None`` (``None`` = unknown frame) — so
    validation stays provider- and media-agnostic; it never imports the
    media layer.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    video_duration_seconds: float | None = None
    timestamp_tolerance_seconds: float = 0.5
    frame_registry: Any | None = None


# Keys that always denote seconds, plus the generic suffix conventions.
_TIME_KEY_SUFFIXES = ("_seconds", "_timestamp")
_EXACT_TIME_KEYS = frozenset({"timestamp_seconds", "start_seconds", "end_seconds"})


def _is_time_key(key: Any) -> bool:
    return isinstance(key, str) and (
        key in _EXACT_TIME_KEYS or key.endswith(_TIME_KEY_SUFFIXES)
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def iter_time_fields(data: Any, *, _path: str = "") -> Iterator[tuple[str, float]]:
    """Yield ``(json_pointer, seconds)`` for fields that look like time values.

    Matching is a heuristic over common conventions, not universal truth: a
    key matches when it is exactly ``timestamp_seconds``/``start_seconds``/
    ``end_seconds``, or ends with ``_seconds``/``_timestamp``, and holds a
    numeric (non-boolean) value. Non-dict/list nodes and non-numeric values
    are skipped silently.

    Pointers are ``/``-joined like the ``field`` values produced by
    :func:`validate_data` (no RFC 6901 escaping, for consistency).
    """
    if isinstance(data, dict):
        for key, value in data.items():
            pointer = f"{_path}/{key}"
            if _is_time_key(key) and _is_number(value):
                yield pointer, float(value)
            yield from iter_time_fields(value, _path=pointer)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from iter_time_fields(value, _path=f"{_path}/{index}")


def _check_intervals_and_frame_refs(
    data: Any, context: SemanticContext, *, _path: str = ""
) -> Iterator[ValidationIssue]:
    """Recursive pass for per-dict interval order and frame-ref resolution."""
    if isinstance(data, dict):
        pointer = _path or "/"
        start = data.get("start_seconds")
        end = data.get("end_seconds")
        # _is_number narrows at runtime; cast tells mypy (values come from
        # untyped extracted data, so static narrowing cannot see it).
        if (
            _is_number(start)
            and _is_number(end)
            and cast(float, start) > cast(float, end)
        ):
            yield ValidationIssue(
                code="semantic_interval_invalid",
                message=(
                    f"{pointer}: start_seconds ({start}) exceeds "
                    f"end_seconds ({end})."
                ),
                field=pointer,
            )
        if context.frame_registry is not None:
            for key in ("frame_id", "frame_ref"):
                ref = data.get(key)
                ref_pointer = f"{pointer}/{key}" if pointer != "/" else f"/{key}"
                if isinstance(ref, str) and context.frame_registry.lookup(ref) is None:
                    yield ValidationIssue(
                        code="semantic_unknown_frame_ref",
                        message=(
                            f"{ref_pointer}: frame reference {ref!r} "
                            "is not in the execution's frame registry."
                        ),
                        field=ref_pointer,
                    )
        for key, value in data.items():
            yield from _check_intervals_and_frame_refs(
                value, context, _path=f"{_path}/{key}"
            )
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from _check_intervals_and_frame_refs(
                value, context, _path=f"{_path}/{index}"
            )


def validate_semantics(
    data: Any, *, context: SemanticContext | None = None
) -> list[ValidationIssue]:
    """Deterministic semantic checks over extracted data.

    Checks only, no semantic truth: code verifies that time values are
    finite, non-negative, ordered, and within the video duration (+ tolerance),
    and that frame references resolve in the registry. It cannot prove that
    the model actually saw the event the timestamp claims to describe.

    Issue codes: ``semantic_timestamp_invalid``, ``semantic_timestamp_out_of_range``,
    ``semantic_interval_invalid``, ``semantic_unknown_frame_ref``.
    """
    ctx = context if context is not None else SemanticContext()
    issues: list[ValidationIssue] = []
    for pointer, seconds in iter_time_fields(data):
        if not math.isfinite(seconds) or seconds < 0:
            issues.append(
                ValidationIssue(
                    code="semantic_timestamp_invalid",
                    message=(
                        f"{pointer}: time value must be a finite, non-negative "
                        f"number of seconds, got {seconds!r}."
                    ),
                    field=pointer,
                )
            )
        elif (
            ctx.video_duration_seconds is not None
            and seconds > ctx.video_duration_seconds + ctx.timestamp_tolerance_seconds
        ):
            issues.append(
                ValidationIssue(
                    code="semantic_timestamp_out_of_range",
                    message=(
                        f"{pointer}: {seconds} exceeds video duration "
                        f"{ctx.video_duration_seconds}s "
                        f"(tolerance {ctx.timestamp_tolerance_seconds}s)."
                    ),
                    field=pointer,
                )
            )
    issues.extend(_check_intervals_and_frame_refs(data, ctx))
    return issues


def validate_schema(schema: Any) -> None:
    """Reject invalid schemas with a clear error, before any provider call."""
    if not isinstance(schema, dict):
        raise UnsupportedSchemaError(
            f"JSON Schema must be a dict, got {type(schema).__name__}.",
            details={"received_type": type(schema).__name__},
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise UnsupportedSchemaError(
            f"Invalid JSON Schema (draft {SCHEMA_DRAFT}): {exc.message}",
            details={"schema_error": exc.message},
        ) from exc


def validate_data(data: Any, schema: dict[str, Any]) -> ValidationReport:
    """Validate extracted data against the developer's schema, locally."""
    validator = Draft202012Validator(schema)
    issues = [
        ValidationIssue(
            code="schema_violation",
            message=error.message,
            field="/" + "/".join(str(p) for p in error.absolute_path)
            if error.absolute_path
            else "/",
        )
        for error in validator.iter_errors(data)
    ]
    return ValidationReport(valid=not issues, issues=issues)
