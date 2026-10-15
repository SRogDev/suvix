"""Bounded selective recovery.

After a failed extraction/validation, Suvix may retry with a targeted repair
prompt that names the concrete issues. Rules:

- Same extractor, same model, same strategy — never a silent switch.
- One provider call per attempt; the caller enforces the attempt budget.
- Every attempt is counted in usage/execution metadata.

Budget contract
---------------
- The caller owns the attempt budget (attempts, timeouts); this module never
  loops on its own — :func:`run_recovery_attempt` makes exactly one call.
- :func:`is_recoverable` is the gate: no repair when the report is valid or
  when every issue is a warning, so warnings never burn the provider budget.
- :func:`build_repair_request` keeps extractor, model, schema, strategy, and
  frames identical to the original request; only the instructions change.
- The caller must count every attempt in usage/execution metadata.

Milestone 1 implements the generic repair loop; Milestone 6 adds issue
classification and the warnings-only gate.
"""

from __future__ import annotations

from typing import Any

from suvix.adapters.base import AdapterRequest, ProviderExtraction, VideoExtractor
from suvix.contracts import ValidationIssue, ValidationReport

MAX_ISSUES_IN_PROMPT = 10

_NO_FABRICATION_LINE = (
    "Do not invent values for information not visible; "
    "omit fields the schema allows omitting rather than fabricating."
)


def classify_issues(report: ValidationReport) -> dict[str, list[ValidationIssue]]:
    """Group a report's issues by their ``code``."""
    grouped: dict[str, list[ValidationIssue]] = {}
    for issue in report.issues:
        grouped.setdefault(issue.code, []).append(issue)
    return grouped


def is_recoverable(data: Any, report: ValidationReport) -> bool:
    """Whether a repair attempt is worth one provider call.

    False when the report is valid (nothing to fix) or when every issue is a
    warning — warnings must not burn the recovery budget.
    """
    if report.valid:
        return False
    return any(issue.severity != "warning" for issue in report.issues)


def build_repair_instructions(
    failed_report: ValidationReport, *, max_issues: int = MAX_ISSUES_IN_PROMPT
) -> str:
    """Short repair prompt naming the concrete validation issues.

    Issues are grouped by field for readability and capped at ``max_issues``
    entries. The prompt forbids fabricating values for information that is
    not visible in the video.
    """
    lines = [
        "Your previous output failed validation. "
        "Return ONLY corrected JSON matching the requested schema — no explanations, "
        "no markdown fences.",
        _NO_FABRICATION_LINE,
        f"Issues to fix ({len(failed_report.issues)} total):",
    ]
    by_field: dict[str, list[ValidationIssue]] = {}
    for issue in failed_report.issues:
        by_field.setdefault(issue.field or "/", []).append(issue)
    shown = 0
    for field, group in by_field.items():
        if shown >= max_issues:
            break
        lines.append(f"- {field}:")
        for issue in group:
            if shown >= max_issues:
                break
            lines.append(f"  - [{issue.code}] {issue.message}")
            shown += 1
    if len(failed_report.issues) > max_issues:
        lines.append(f"- ... and {len(failed_report.issues) - max_issues} more.")
    return "\n".join(lines)


async def run_recovery_attempt(
    *,
    extractor: VideoExtractor,
    request: AdapterRequest,
    failed_report: ValidationReport,
) -> ProviderExtraction:
    """Make one repair call with the same extractor and strategy.

    Convenience wrapper around :func:`build_repair_request` for standalone
    use. The extraction pipeline calls the repair request through the same
    timeout/error mapping as the initial call; this wrapper calls the
    extractor directly. Provider errors propagate to the caller.
    """
    return await extractor.extract(build_repair_request(request, failed_report))


def build_repair_request(
    request: AdapterRequest, failed_report: ValidationReport
) -> AdapterRequest:
    """Build the repair request: same schema/strategy/frames, with the repair
    instructions appended to the developer's original instructions."""
    return AdapterRequest(
        video_path=request.video_path,
        schema=request.json_schema,
        instructions=(
            request.instructions + "\n\n" + build_repair_instructions(failed_report)
        ),
        options=request.options,
        frames=request.frames,
        strategy=request.strategy,
    )
