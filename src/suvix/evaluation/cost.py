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

One explicitly opt-in exception: :func:`load_verified_pricing_snapshot`
registers the Gemini prices verified against the official pricing page on
2026-10-23. Nothing is registered until a user calls it.
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


# The one verified snapshot bundled with the library. Prices are the paid
# Standard-tier rates from https://ai.google.dev/gemini-api/docs/pricing,
# fetched and verified 2026-10-23, converted from USD per 1M tokens to the
# flat per-1k table shape ($0.30/1M = 0.0003 per 1k, etc.).
_VERIFIED_SNAPSHOT_DATE = "2026-10-23"
_VERIFIED_SNAPSHOT_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
_VERIFIED_SNAPSHOT: dict[tuple[str, str], dict[str, float]] = {
    ("gemini", "gemini-2.5-flash"): {"input_per_1k": 0.0003, "output_per_1k": 0.0025},
    ("gemini", "gemini-2.5-pro"): {"input_per_1k": 0.00125, "output_per_1k": 0.01},
    ("gemini", "gemini-2.5-flash-lite"): {"input_per_1k": 0.0001, "output_per_1k": 0.0004},
}


def load_verified_pricing_snapshot(*, as_of: str = "2026-10-23") -> None:
    """Register the pricing snapshot verified on 2026-10-23 (opt-in only).

    Registers paid Standard-tier Gemini prices fetched from
    https://ai.google.dev/gemini-api/docs/pricing and verified 2026-10-23:

    - ``gemini-2.5-flash``: $0.30 input / $2.50 output per 1M tokens
      (text/image/video input rate; audio input is $1.00/1M and is NOT
      represented — the flat table cannot split input by modality).
    - ``gemini-2.5-pro``: $1.25 input / $10.00 output per 1M tokens.
    - ``gemini-2.5-flash-lite``: $0.10 input / $0.40 output per 1M tokens
      (text/image/video input rate; audio input is $0.30/1M, likewise
      not represented).

    Tier limitation (do not silently flatten): Gemini 2.5 Pro pricing is
    tiered by prompt size — $2.50 input / $15.00 output per 1M tokens for
    prompts above 200k tokens. The flat per-1k table shape cannot
    represent tiers, so only the <=200k tier is registered; estimates for
    prompts above 200k tokens will UNDERSTATE the Pro cost.

    Only the ``as_of="2026-10-23"`` snapshot exists; any other date raises
    ``ValueError`` rather than serving numbers that were never verified
    for that date. Default behavior is unchanged: until this function is
    called, :func:`resolve_pricing` still returns ``None``.
    """
    if as_of != _VERIFIED_SNAPSHOT_DATE:
        raise ValueError(
            f"no verified pricing snapshot for {as_of!r}; "
            f"the only verified snapshot is as_of={_VERIFIED_SNAPSHOT_DATE!r}"
        )
    for (provider, model), table in _VERIFIED_SNAPSHOT.items():
        register_pricing(
            provider,
            model,
            table,
            source=_VERIFIED_SNAPSHOT_SOURCE,
            date=_VERIFIED_SNAPSHOT_DATE,
        )
