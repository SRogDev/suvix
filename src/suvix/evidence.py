"""Evidence helpers.

Milestone 1 covers timestamp sanity (finite, non-negative, ordered intervals).
Milestone 6 adds full evidence validation: duration bounds with tolerance,
frame-registry resolution for ``frame`` refs, and duplicate detection.
"""

from __future__ import annotations

import math
from typing import Any

from suvix.contracts import EvidenceRef, ValidationIssue


def validate_evidence_timestamps(refs: list[EvidenceRef]) -> list[ValidationIssue]:
    """Check evidence timestamps without needing media metadata.

    Duration-bounded checks (timestamp within the video) require the media
    layer (Milestone 2) and live in the M6 evidence validation.
    """
    issues: list[ValidationIssue] = []
    for index, ref in enumerate(refs):
        where = f"evidence[{index}]"
        for label, value in (
            ("timestamp_seconds", ref.timestamp_seconds),
            ("start_seconds", ref.start_seconds),
            ("end_seconds", ref.end_seconds),
        ):
            if value is None:
                continue
            if not math.isfinite(value) or value < 0:
                issues.append(
                    ValidationIssue(
                        code="evidence_timestamp_invalid",
                        message=f"{where}.{label} must be a finite, "
                        f"non-negative number, got {value!r}.",
                        field=where,
                    )
                )
        if (
            ref.start_seconds is not None
            and ref.end_seconds is not None
            and ref.start_seconds > ref.end_seconds
        ):
            issues.append(
                ValidationIssue(
                    code="evidence_interval_invalid",
                    message=f"{where}: start_seconds ({ref.start_seconds}) exceeds "
                    f"end_seconds ({ref.end_seconds}).",
                    field=where,
                )
            )
    return issues


def validate_evidence(
    refs: list[EvidenceRef],
    *,
    video_duration_seconds: float | None = None,
    frame_registry: Any | None = None,
    tolerance_seconds: float = 0.5,
) -> list[ValidationIssue]:
    """Full evidence validation.

    Runs :func:`validate_evidence_timestamps` and adds:

    - duration bounds: every timestamp/interval bound must be within
      ``video_duration_seconds + tolerance_seconds`` (skipped when the
      duration is unknown) — code ``evidence_out_of_range``;
    - frame resolution: a ``frame`` ref whose ``frame_id`` is not in the
      registry (duck-typed ``.lookup(frame_id) -> float | None``) —
      code ``evidence_unknown_frame`` (error);
    - duplicates: each set of identical refs produces a single
      ``evidence_duplicate`` warning, not an error.

    Like the semantic checks, this validates ranges and references — never
    whether the model's interpretation of the video is correct.
    """
    issues = validate_evidence_timestamps(refs)

    if video_duration_seconds is not None:
        limit = video_duration_seconds + tolerance_seconds
        for index, ref in enumerate(refs):
            where = f"evidence[{index}]"
            for label, value in (
                ("timestamp_seconds", ref.timestamp_seconds),
                ("start_seconds", ref.start_seconds),
                ("end_seconds", ref.end_seconds),
            ):
                if value is not None and value > limit:
                    issues.append(
                        ValidationIssue(
                            code="evidence_out_of_range",
                            message=(
                                f"{where}.{label} ({value}) exceeds video duration "
                                f"{video_duration_seconds}s "
                                f"(tolerance {tolerance_seconds}s)."
                            ),
                            field=where,
                        )
                    )

    if frame_registry is not None:
        for index, ref in enumerate(refs):
            where = f"evidence[{index}]"
            if (
                ref.ref_type == "frame"
                and ref.frame_id is not None
                and frame_registry.lookup(ref.frame_id) is None
            ):
                issues.append(
                    ValidationIssue(
                        code="evidence_unknown_frame",
                        message=(
                            f"{where}: frame reference {ref.frame_id!r} "
                            "is not in the execution's frame registry."
                        ),
                        field=where,
                    )
                )

    seen: dict[str, int] = {}
    for ref in refs:
        key = ref.model_dump_json()
        seen[key] = seen.get(key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            issues.append(
                ValidationIssue(
                    code="evidence_duplicate",
                    message=(
                        f"{count} identical evidence refs ({key}); "
                        "kept as a warning, not an error."
                    ),
                    severity="warning",
                )
            )
    return issues
