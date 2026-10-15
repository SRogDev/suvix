"""Bounded coarse-to-fine refinement for the selected-frames strategy (M5).

Process: one coarse pass over uniformly sampled frames identifies candidate
intervals (internal planning schema); each fine round samples densely inside
the expanded intervals and runs the developer's schema; further rounds only
happen while the previous round failed validation AND budget/rounds remain.

Honesty constraints (SUVIX_PLAN.md §9.4), stated plainly:

- NOT exhaustive. The coarse pass may miss a brief event entirely, and no
  refinement round may be described as exhaustive.
- Bounded. Exactly one coarse pass plus at most ``max_refinement_rounds``
  fine rounds — never an open agent loop. The total number of sampled frames
  across coarse + fine rounds never exceeds ``options.max_frames``: the
  coarse pass uses roughly half the budget and each fine round receives an
  even share of the remaining budget over the remaining rounds.
- Internal planning stays internal. ``COARSE_SCHEMA`` and the coarse pass's
  evidence are never exposed in the developer's ``data``; only the final
  fine round's evidence is returned (frame ids validated by the caller).
- Overlapping candidate intervals are merged so adjacent regions are not
  re-sampled redundantly; already-sampled timestamps are never re-extracted.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, NamedTuple

from suvix.adapters.base import (
    AdapterRequest,
    FrameInput,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.errors import UnsupportedMediaError
from suvix.media.frames import FrameRegistry, SampledFrame, extract_frames_at
from suvix.media.metadata import VideoMetadata
from suvix.options import ExtractionOptions

COARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidate_intervals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["start_seconds", "end_seconds"],
            },
        }
    },
    "required": ["candidate_intervals"],
}
"""Internal planning schema for the coarse pass.

Never leaked into the developer's ``data``: the final extraction is always
governed by the developer's own JSON Schema.
"""

_TOKEN_SUM_KEYS = (
    "input_tokens",
    "prompt_tokens",
    "prompt_token_count",
    "output_tokens",
    "completion_tokens",
    "candidates_token_count",
    "total_tokens",
    "total_token_count",
)


class CoarseToFineOutcome(NamedTuple):
    """Outcome of :func:`coarse_to_fine_extract`.

    ``(extraction, rounds_used, total_frames)`` with one documented extension:
    ``last_request`` — the final fine round's :class:`AdapterRequest`. The
    caller needs it so bounded recovery can build repair requests carrying
    the final round's frames. Always set by :func:`coarse_to_fine_extract`.
    """

    extraction: ProviderExtraction
    rounds_used: int
    total_frames: int
    last_request: AdapterRequest


def _coarse_instructions(
    instructions: str, coarse_frames: list[SampledFrame], duration: float
) -> str:
    stamps = ", ".join(f"{f.timestamp_seconds:.2f}s" for f in coarse_frames)
    return (
        "COARSE PASS — candidate interval identification "
        "(internal planning step, not the final extraction).\n\n"
        f"Task: {instructions}\n\n"
        f"Video duration: {duration:.2f}s. The {len(coarse_frames)} attached "
        f"frames were sampled uniformly at: {stamps}. Identify candidate time "
        "intervals [start_seconds, end_seconds] (within the video duration) "
        "most likely to contain the information needed for the task. If "
        "nothing looks relevant, return an empty candidate_intervals list. "
        "Do NOT attempt the full extraction yet; respond with ONLY the "
        "candidate_intervals object."
    )


def _fine_instructions(instructions: str, round_no: int, note: str) -> str:
    return (
        f"FINE PASS (refinement round {round_no}).\n\n"
        f"Task: {instructions}\n\n"
        f"{note} Produce the final extraction matching the requested schema "
        "using ONLY information visible in the attached frames. Do not invent "
        "events outside the provided frames."
    )


def _to_frame_inputs(frames: list[SampledFrame]) -> list[FrameInput]:
    return [
        FrameInput(
            frame_id=f.frame_id,
            timestamp_seconds=f.timestamp_seconds,
            image_bytes=f.image_bytes,
            mime_type=f.mime_type,
        )
        for f in frames
    ]


def _coerce_coarse_data(out: ProviderExtraction) -> dict[str, Any] | None:
    """Best-effort parse of the coarse pass output; never raises.

    A malformed coarse output degrades to "no intervals" (with a warning) and
    the workflow falls back to a single fine pass — the coarse pass is
    planning, not the deliverable.
    """
    if isinstance(out.data, dict):
        return out.data
    if out.raw_text:
        try:
            parsed = json.loads(out.raw_text.strip())
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _validate_candidate_intervals(
    data: dict[str, Any] | None, *, duration_seconds: float
) -> tuple[list[tuple[float, float]], list[str]]:
    """Defensive parse of the coarse pass output.

    Invalid intervals are dropped with a specific warning each — never
    clamped silently, never allowed to widen the search beyond the video.
    """
    no_intervals = (
        "coarse pass produced no usable candidate intervals; falling back "
        "to a single fine pass over the coarse frames."
    )
    if not isinstance(data, dict):
        return [], [no_intervals]
    raw = data.get("candidate_intervals")
    if not isinstance(raw, list):
        return [], [no_intervals]
    intervals: list[tuple[float, float]] = []
    warnings: list[str] = []
    for item in raw:
        reason = f"coarse pass: dropped invalid candidate interval {item!r}"
        if not isinstance(item, dict):
            warnings.append(f"{reason}: not an object")
            continue
        start, end = item.get("start_seconds"), item.get("end_seconds")
        for label, value in (("start_seconds", start), ("end_seconds", end)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                warnings.append(f"{reason}: {label} is not a finite number")
                break
        else:
            if start > end:
                warnings.append(
                    f"{reason}: start_seconds ({start}) exceeds "
                    f"end_seconds ({end})"
                )
                continue
            if start < 0 or end > duration_seconds:
                warnings.append(
                    f"{reason}: outside the video duration "
                    f"[0, {duration_seconds}]"
                )
                continue
            intervals.append((float(start), float(end)))
    return _merge_overlapping(intervals), warnings


def _merge_overlapping(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Merge overlapping or touching intervals, sorted by start."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _expand_intervals(
    intervals: list[tuple[float, float]],
    *,
    context_seconds: float,
    duration_seconds: float,
) -> list[tuple[float, float]]:
    """Widen each interval by ±context, clamped to the video bounds."""
    return [
        (
            max(0.0, start - context_seconds),
            min(duration_seconds, end + context_seconds),
        )
        for start, end in intervals
    ]


def _plan_fine_samples(
    intervals: list[tuple[float, float]], budget: int
) -> list[tuple[float, float, int]]:
    """Distribute ``budget`` frame slots across intervals.

    Every interval gets at least one slot while the budget allows; extras go
    to the longest-per-slot interval first. Deterministic.
    """
    ordered = sorted(intervals)
    n = len(ordered)
    if n == 0 or budget <= 0:
        return []
    if budget < n:
        # Keep the longest intervals only.
        order = sorted(
            range(n), key=lambda i: ordered[i][1] - ordered[i][0], reverse=True
        )
        kept = sorted(order[:budget])
        return [(ordered[i][0], ordered[i][1], 1) for i in kept]
    counts = [1] * n
    lengths = [max(end - start, 0.0) for start, end in ordered]
    for _ in range(budget - n):
        best = max(range(n), key=lambda i: (lengths[i] / counts[i], -i))
        counts[best] += 1
    return [(s, e, c) for (s, e), c in zip(ordered, counts, strict=True)]


def _sample_timestamps_in_intervals(
    *,
    intervals: list[tuple[float, float]],
    budget: int,
    exclude: set[float],
    duration_seconds: float,
) -> list[float]:
    """Millisecond-rounded timestamps inside intervals, skipping ``exclude``."""
    stamps: list[float] = []
    seen = set(exclude)
    for start, end, count in _plan_fine_samples(intervals, budget):
        if end <= start:
            candidates = [start]
        else:
            candidates = [
                start + (end - start) * (slot + 0.5) / count
                for slot in range(count)
            ]
        for candidate in candidates:
            timestamp = round(candidate, 3)
            if (
                timestamp < 0
                or timestamp > duration_seconds
                or timestamp in seen
            ):
                continue
            seen.add(timestamp)
            stamps.append(timestamp)
    return sorted(stamps)


def _shrink_intervals(
    intervals: list[tuple[float, float]],
    *,
    evidence_timestamps: list[float],
    duration_seconds: float,
) -> list[tuple[float, float]]:
    """Zoom in: middle half of each interval, plus windows around evidence.

    Used when a fine round failed validation — the next round looks closer
    at where the previous round already saw something, or at the middle of
    each candidate region when it saw nothing timestamped.
    """
    shrunk: list[tuple[float, float]] = []
    widths = sorted(e - s for s, e in intervals if e - s >= 1e-3)
    fallback_half_width = (widths[len(widths) // 2] / 4.0) if widths else 1.0
    for start, end in intervals:
        width = end - start
        if width < 1e-3:
            continue
        mid = (start + end) / 2.0
        shrunk.append(
            (
                max(0.0, mid - width / 4.0),
                min(duration_seconds, mid + width / 4.0),
            )
        )
    for timestamp in evidence_timestamps:
        if not 0.0 <= timestamp <= duration_seconds:
            continue
        half_width = fallback_half_width
        for start, end in intervals:
            if start <= timestamp <= end and end - start >= 1e-3:
                half_width = (end - start) / 4.0
                break
        shrunk.append(
            (
                max(0.0, timestamp - half_width),
                min(duration_seconds, timestamp + half_width),
            )
        )
    return _merge_overlapping(shrunk)


def _accumulate_usage(
    target: dict[str, Any], usage: Mapping[str, Any] | None
) -> None:
    """Merge one pass's provider usage into the running total.

    Token counts are summed across passes — a measured total of
    provider-reported usage for the whole extraction, not per-pass figures.
    Non-token metadata keeps the latest pass's values.
    """
    for key, value in (usage or {}).items():
        if isinstance(value, bool):
            continue
        if key in _TOKEN_SUM_KEYS and isinstance(value, (int, float)):
            target[key] = target.get(key, 0) + value
        elif key not in _TOKEN_SUM_KEYS:
            target[key] = value


def _format_intervals(intervals: list[tuple[float, float]]) -> str:
    return ", ".join(f"[{s:.2f}s, {e:.2f}s]" for s, e in intervals)


async def coarse_to_fine_extract(
    *,
    video_path: str,
    metadata: VideoMetadata,
    options: ExtractionOptions,
    extractor: VideoExtractor,
    schema: dict[str, Any],
    instructions: str,
    coarse_frames: list[SampledFrame],
    registry: FrameRegistry,
) -> CoarseToFineOutcome:
    """Run the bounded coarse-to-fine workflow.

    Returns ``(extraction, rounds_used, total_frames)`` plus the final fine
    round's request for bounded recovery. See the module docstring for the
    honesty constraints this workflow operates under.
    """
    # Deferred import: suvix.extraction imports this module at load time.
    from suvix.extraction import _call_adapter, _validate_extraction

    duration = metadata.duration_seconds
    if duration is None:
        raise UnsupportedMediaError(
            "Coarse-to-fine refinement requires a known video duration.",
            details={"video_path": video_path},
        )
    timeout = options.per_call_timeout_seconds

    warnings: list[str] = []
    usage_total: dict[str, Any] = {}
    sampled: set[float] = {
        round(frame.timestamp_seconds, 3) for frame in coarse_frames
    }
    total_frames = len(coarse_frames)

    # Round 0 — coarse pass: candidate intervals under the internal schema.
    coarse_request = AdapterRequest(
        video_path=video_path,
        schema=dict(COARSE_SCHEMA),
        instructions=_coarse_instructions(instructions, coarse_frames, duration),
        options=options,
        frames=_to_frame_inputs(coarse_frames),
        strategy="selected_frames",
    )
    coarse_out = await _call_adapter(extractor, coarse_request, timeout)
    warnings.extend(coarse_out.warnings)
    _accumulate_usage(usage_total, coarse_out.usage)

    intervals, interval_warnings = _validate_candidate_intervals(
        _coerce_coarse_data(coarse_out), duration_seconds=duration
    )
    warnings.extend(interval_warnings)
    intervals = _expand_intervals(
        intervals,
        context_seconds=options.coarse_interval_seconds,
        duration_seconds=duration,
    )

    last_request = coarse_request
    fine_out: ProviderExtraction | None = None
    rounds_used = 0

    async def _fine_pass(
        frames: list[SampledFrame], round_no: int, note: str
    ) -> ProviderExtraction:
        nonlocal last_request, fine_out, rounds_used
        request = AdapterRequest(
            video_path=video_path,
            schema=schema,
            instructions=_fine_instructions(instructions, round_no, note),
            options=options,
            frames=_to_frame_inputs(frames),
            strategy="selected_frames",
        )
        out = await _call_adapter(extractor, request, timeout)
        warnings.extend(out.warnings)
        _accumulate_usage(usage_total, out.usage)
        last_request = request
        fine_out = out
        rounds_used = round_no
        return out

    active = intervals
    for round_no in range(1, options.max_refinement_rounds + 1):
        if round_no == 1 and not active:
            await _fine_pass(
                coarse_frames,
                round_no,
                "No candidate intervals from the coarse pass; single fine "
                "pass over the coarse frames.",
            )
            break
        # Even share of the remaining budget over the remaining rounds, so
        # every round can sample while budget remains and the total never
        # exceeds max_frames.
        rounds_remaining = options.max_refinement_rounds - round_no + 1
        budget = max(0, (options.max_frames - total_frames) // rounds_remaining)
        timestamps = _sample_timestamps_in_intervals(
            intervals=active,
            budget=budget,
            exclude=sampled,
            duration_seconds=duration,
        )
        if not timestamps:
            if round_no == 1:
                await _fine_pass(
                    coarse_frames,
                    round_no,
                    "Frame budget exhausted before fine sampling; single "
                    "fine pass over the coarse frames.",
                )
            else:
                warnings.append(
                    f"refine_round_{round_no}: no new timestamps to sample; "
                    "stopping refinement."
                )
            break
        new_frames = await extract_frames_at(
            video_path, timestamps, max_frames=budget, registry=registry
        )
        if not new_frames:
            warnings.append(
                f"refine_round_{round_no}: frame extraction returned no new "
                "frames; stopping refinement."
            )
            if round_no == 1:
                await _fine_pass(
                    coarse_frames,
                    round_no,
                    "No new frames could be sampled; single fine pass over "
                    "the coarse frames.",
                )
            break
        for frame in new_frames:
            sampled.add(round(frame.timestamp_seconds, 3))
        total_frames += len(new_frames)

        out = await _fine_pass(
            new_frames,
            round_no,
            f"Candidate intervals: {_format_intervals(active)}.",
        )
        _, report = _validate_extraction(out, schema)
        if report.valid:
            break
        # Validation failed: shrink around still-invalid evidence and retry
        # while rounds and budget remain.
        evidence_timestamps = [
            ref.timestamp_seconds
            for ref in out.evidence
            if isinstance(ref.timestamp_seconds, (int, float))
            and not isinstance(ref.timestamp_seconds, bool)
            and math.isfinite(ref.timestamp_seconds)
            and 0.0 <= ref.timestamp_seconds <= duration
        ]
        active = _shrink_intervals(
            active,
            evidence_timestamps=evidence_timestamps,
            duration_seconds=duration,
        )
        if not active:
            warnings.append(
                "Refinement stopped: no candidate intervals remain after "
                "shrinking."
            )
            break

    if fine_out is None:  # max_refinement_rounds was 0; never fine-passed
        warnings.append(
            "No fine rounds executed; single fine pass over the coarse frames."
        )
        await _fine_pass(
            coarse_frames, 1, "Single fine pass over the coarse frames."
        )
        assert fine_out is not None

    final = ProviderExtraction(
        data=fine_out.data,
        raw_text=fine_out.raw_text,
        evidence=list(fine_out.evidence),
        usage=usage_total,
        warnings=warnings,
    )
    return CoarseToFineOutcome(
        extraction=final,
        rounds_used=rounds_used,
        total_frames=total_frames,
        last_request=last_request,
    )
