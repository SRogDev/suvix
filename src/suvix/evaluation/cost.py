"""Pricing resolution for benchmark cost estimation.

The pricing tables start EMPTY — deliberately. Suvix ships no verified
provider prices because prices change and unverified numbers are worse than
no numbers: with no table, :func:`resolve_pricing` returns ``None`` and the
cost basis stays ``"unavailable"`` (never invented).

How a user supplies their own table::

    from suvix.evaluation import cost

    cost.register_pricing(
        provider="gemini",
        model="gemini-2.5-flash",
        table={"input_per_1k": 0.0003, "output_per_1k": 0.0025},
        source="https://ai.google.dev/gemini-api/docs/pricing (user-verified)",
        date="2026-10-15",
    )

The table shape matches :func:`suvix.pricing.estimate_cost`'s ``pricing``
mapping: ``{"input_per_1k": <usd>, "output_per_1k": <usd>}`` per 1k tokens.
Video/second or per-image components are not modeled — record them in the
benchmark's ``unestimated_components`` instead of folding them into a fake
per-token number.
"""

from __future__ import annotations

# (provider, model) -> (table, source, date). Empty by design: no verified
# prices are bundled with the library. See module docstring for how users
# register their own.
_PRICING_TABLES: dict[tuple[str, str], tuple[dict[str, float], str, str]] = {}


def register_pricing(
    provider: str,
    model: str,
    table: dict[str, float],
    *,
    source: str,
    date: str,
) -> None:
    """Register a user-supplied pricing table for a (provider, model) pair.

    Args:
        table: e.g. ``{"input_per_1k": 0.0003, "output_per_1k": 0.0025}``.
        source: where the numbers came from (URL or "user-supplied").
        date: when the prices were verified, ``YYYY-MM-DD``.

    Overwrites any previous table for the same pair; the newest registration
    wins, and the benchmark output records its source and date.
    """
    _PRICING_TABLES[(provider, model)] = (dict(table), source, date)


def resolve_pricing(
    provider: str, model: str
) -> tuple[dict[str, float] | None, str, str]:
    """Return ``(table, source, date)`` for a (provider, model) pair.

    With no registered table this returns ``(None, "unavailable",
    "unverified")`` — the caller must then keep ``cost_basis="unavailable"``
    instead of inventing a price.
    """
    entry = _PRICING_TABLES.get((provider, model))
    if entry is None:
        return None, "unavailable", "unverified"
    table, source, date = entry
    return dict(table), source, date
