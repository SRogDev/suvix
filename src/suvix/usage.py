"""Usage aggregation: provider-reported tokens plus local counters.

Providers expose different usage shapes; this module maps the common key
variants and leaves everything else in ``UsageReport.raw``. Missing values
stay ``None`` — never invented.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from suvix.contracts import UsageReport

_INPUT_KEYS = ("input_tokens", "prompt_tokens", "prompt_token_count")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens", "candidates_token_count")
_TOTAL_KEYS = ("total_tokens", "total_token_count")


def _first_int(usage: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


def build_usage(
    *,
    provider_usage: Mapping[str, Any] | None,
    provider_requests: int,
    recovery_requests: int,
    sampled_frames: int = 0,
    video_duration_seconds: float | None = None,
    started_at: float | None = None,
) -> UsageReport:
    """Assemble a :class:`UsageReport` from raw provider usage and counters."""
    raw = dict(provider_usage or {})
    input_tokens = _first_int(raw, _INPUT_KEYS)
    output_tokens = _first_int(raw, _OUTPUT_KEYS)
    total_tokens = _first_int(raw, _TOTAL_KEYS)
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    latency = time.perf_counter() - started_at if started_at is not None else 0.0
    return UsageReport(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider_requests=provider_requests,
        recovery_requests=recovery_requests,
        sampled_frames=sampled_frames,
        video_duration_seconds=video_duration_seconds,
        latency_seconds=max(latency, 0.0),
        cost_basis="unavailable",
        raw=raw,
    )
