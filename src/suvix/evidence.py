"""Evidence helpers.

Milestone 1 covers timestamp sanity (finite, non-negative, ordered intervals).
Frame-registry checks (Milestone 2) and full evidence validation (Milestone 6)
build on these primitives.
"""

from __future__ import annotations

import math

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
