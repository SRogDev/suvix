"""Benchmarking and evaluation harness (Milestone 8).

Pure metric functions (:mod:`suvix.evaluation.metrics`), the baseline runner
(:mod:`suvix.evaluation.runner`), and pricing resolution
(:mod:`suvix.evaluation.cost`).

Honesty rules inherited from SUVIX_PLAN.md §16:

- Costs come only from measured or estimated usage; never invent prices.
- Metrics are reported per dimension; they are never collapsed into a single
  score that hides trade-offs.
- Negative results are retained and reported.
"""

from suvix.evaluation.cost import (
    load_verified_pricing_snapshot,
    register_pricing,
    resolve_pricing,
)
from suvix.evaluation.metrics import (
    cost_per_correct_event,
    count_accuracy,
    duplicate_event_rate,
    event_precision_recall_f1,
    failure_rate,
    invalid_evidence_rate,
    json_parse_success,
    mean_latency,
    missing_required_field_rate,
    schema_pass_rate,
    text_exact_accuracy,
    timestamp_mae,
    total_estimated_cost,
    total_provider_requests,
    unsupported_claim_rate,
)
from suvix.evaluation.runner import (
    BASELINES,
    BaselineResult,
    BenchmarkTask,
    run_baseline,
    summarize,
)

__all__ = [
    "BASELINES",
    "BaselineResult",
    "BenchmarkTask",
    "cost_per_correct_event",
    "count_accuracy",
    "duplicate_event_rate",
    "event_precision_recall_f1",
    "failure_rate",
    "invalid_evidence_rate",
    "json_parse_success",
    "load_verified_pricing_snapshot",
    "mean_latency",
    "missing_required_field_rate",
    "register_pricing",
    "resolve_pricing",
    "run_baseline",
    "schema_pass_rate",
    "summarize",
    "text_exact_accuracy",
    "timestamp_mae",
    "total_estimated_cost",
    "total_provider_requests",
    "unsupported_claim_rate",
]
