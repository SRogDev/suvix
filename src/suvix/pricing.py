"""Cost estimation — optional, transparent, and honest.

A cost estimate always identifies its pricing source and date; components
that cannot be estimated are listed, not zeroed. With no pricing table the
estimate is ``None`` and the usage report keeps ``cost_basis="unavailable"``.

Full per-provider pricing tables land in Milestone 8 (benchmarks).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from suvix.contracts import UsageReport


class CostEstimate(BaseModel):
    """A labeled cost estimate — never presented as a measured bill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    pricing_source: str
    pricing_date: str
    input_cost_usd: float | None = None
    output_cost_usd: float | None = None
    total_cost_usd: float | None = None
    estimated_components: list[str] = Field(default_factory=list)
    unestimated_components: list[str] = Field(default_factory=list)


def estimate_cost(
    *,
    provider: str,
    model: str,
    usage: UsageReport,
    pricing: Mapping[str, float] | None,
    pricing_source: str = "manual",
    pricing_date: str = "unverified",
) -> CostEstimate | None:
    """Estimate cost from a ``{"input_per_1k": .., "output_per_1k": ..}`` table.

    Returns ``None`` when pricing or usage is missing — the caller must then
    keep ``cost_basis="unavailable"`` instead of inventing a number.
    """
    if not pricing:
        return None
    if usage.input_tokens is None and usage.output_tokens is None:
        return None
    input_cost = (
        usage.input_tokens / 1000 * pricing["input_per_1k"]
        if usage.input_tokens is not None and "input_per_1k" in pricing
        else None
    )
    output_cost = (
        usage.output_tokens / 1000 * pricing["output_per_1k"]
        if usage.output_tokens is not None and "output_per_1k" in pricing
        else None
    )
    total = (input_cost or 0.0) + (output_cost or 0.0)
    unestimated = [
        name
        for name, present in (
            ("input_tokens", input_cost is not None or usage.input_tokens is None),
            ("output_tokens", output_cost is not None or usage.output_tokens is None),
        )
        if not present
    ]
    return CostEstimate(
        provider=provider,
        model=model,
        pricing_source=pricing_source,
        pricing_date=pricing_date,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=total if (input_cost is not None or output_cost is not None) else None,
        estimated_components=[
            c for c, v in (("input_tokens", input_cost), ("output_tokens", output_cost))
            if v is not None
        ],
        unestimated_components=unestimated,
    )
