"""Unit tests for suvix.evaluation.cost — pricing registry + verified snapshot.

The registry starts EMPTY by design; the verified snapshot is opt-in only.
Expectations are hand-computed from the per-1M prices on
https://ai.google.dev/gemini-api/docs/pricing (verified 2026-10-23):

- gemini-2.5-flash:      $0.30 in / $2.50 out per 1M  -> 0.0003 / 0.0025 per 1k
- gemini-2.5-pro:        $1.25 in / $10.00 out per 1M (prompts <= 200k tokens)
                         -> 0.00125 / 0.01 per 1k
- gemini-2.5-flash-lite: $0.10 in / $0.40 out per 1M  -> 0.0001 / 0.0004 per 1k
"""

from __future__ import annotations

import pytest

from suvix.contracts import UsageReport
from suvix.evaluation import cost
from suvix.pricing import estimate_cost

SNAPSHOT_DATE = "2026-10-23"
PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"

EXPECTED_TABLES = {
    ("gemini", "gemini-2.5-flash"): {"input_per_1k": 0.0003, "output_per_1k": 0.0025},
    ("gemini", "gemini-2.5-pro"): {"input_per_1k": 0.00125, "output_per_1k": 0.01},
    ("gemini", "gemini-2.5-flash-lite"): {"input_per_1k": 0.0001, "output_per_1k": 0.0004},
}


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot/restore the module-global registry around every test."""
    saved = dict(cost._PRICING_TABLES)
    cost._PRICING_TABLES.clear()
    yield
    cost._PRICING_TABLES.clear()
    cost._PRICING_TABLES.update(saved)


class TestRegistryStaysEmptyByDefault:
    def test_resolve_without_loader_returns_none(self):
        for provider, model in EXPECTED_TABLES:
            table, source, date = cost.resolve_pricing(provider, model)
            assert table is None
            assert source == "unavailable"
            assert date == "unverified"


class TestVerifiedSnapshotLoader:
    def test_loader_registers_expected_pairs_with_source_and_date(self):
        cost.load_verified_pricing_snapshot()
        for (provider, model), expected in EXPECTED_TABLES.items():
            table, source, date = cost.resolve_pricing(provider, model)
            assert table == expected
            assert PRICING_URL in source
            assert date == SNAPSHOT_DATE

    def test_loader_is_the_only_way_the_snapshot_appears(self):
        # Registering nothing else: an unrelated pair stays unavailable
        # even after the loader runs.
        cost.load_verified_pricing_snapshot()
        table, source, date = cost.resolve_pricing("gemini", "gemini-2.5-flash-preview")
        assert table is None
        assert source == "unavailable"
        assert date == "unverified"

    def test_loader_rejects_unverified_dates(self):
        with pytest.raises(ValueError, match="2026-10-23"):
            cost.load_verified_pricing_snapshot(as_of="2026-01-01")

    def test_docstring_states_tier_limitation_and_date(self):
        doc = cost.load_verified_pricing_snapshot.__doc__ or ""
        assert "200k" in doc
        assert SNAPSHOT_DATE in doc

    @pytest.mark.parametrize(
        ("model", "expected_total"),
        [
            # 10_000 input tokens, 2_000 output tokens, hand-computed:
            ("gemini-2.5-flash", 10 * 0.0003 + 2 * 0.0025),  # 0.008
            ("gemini-2.5-pro", 10 * 0.00125 + 2 * 0.01),  # 0.0325
            ("gemini-2.5-flash-lite", 10 * 0.0001 + 2 * 0.0004),  # 0.0018
        ],
    )
    def test_estimate_cost_exact_total_for_known_usage(self, model, expected_total):
        cost.load_verified_pricing_snapshot()
        table, source, date = cost.resolve_pricing("gemini", model)
        estimate = estimate_cost(
            provider="gemini",
            model=model,
            usage=UsageReport(input_tokens=10_000, output_tokens=2_000),
            pricing=table,
            pricing_source=source,
            pricing_date=date,
        )
        assert estimate is not None
        assert estimate.total_cost_usd == pytest.approx(expected_total)
        assert estimate.pricing_source == source
        assert estimate.pricing_date == SNAPSHOT_DATE
