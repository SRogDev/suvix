"""Bounded selective recovery.

After a failed extraction/validation, Suvix may retry with a targeted repair
prompt that names the concrete issues. Rules:

- Same extractor, same model, same strategy — never a silent switch.
- One provider call per attempt; the caller enforces the attempt budget.
- Every attempt is counted in usage/execution metadata.

Milestone 1 implements the generic repair loop; Milestone 6 adds selective
field/interval-targeted recovery.
"""

from __future__ import annotations

from typing import Any

from suvix.adapters.base import AdapterRequest, ProviderExtraction, VideoExtractor
from suvix.contracts import ValidationReport

MAX_ISSUES_IN_PROMPT = 10


def is_recoverable(data: Any, report: ValidationReport) -> bool:
    """Whether a repair attempt is worth making."""
    return not report.valid


def build_repair_instructions(
    failed_report: ValidationReport, *, max_issues: int = MAX_ISSUES_IN_PROMPT
) -> str:
    """Short repair prompt naming the concrete validation issues."""
    lines = [
        "Your previous output failed validation. "
        "Return ONLY corrected JSON matching the requested schema — no explanations, "
        "no markdown fences, no invented values for information not present.",
        f"Issues to fix ({len(failed_report.issues)} total):",
    ]
    for issue in failed_report.issues[:max_issues]:
        where = f" at {issue.field}" if issue.field else ""
        lines.append(f"- [{issue.code}]{where}: {issue.message}")
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
