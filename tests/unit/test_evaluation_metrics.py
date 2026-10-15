"""Unit tests for suvix.evaluation.metrics — pure, deterministic functions.

Every expectation below is hand-computed. If a test fails after an
implementation change, the formula in the metric's docstring is the contract,
not the test.
"""

from __future__ import annotations

import pytest

from suvix.adapters.base import ProviderExtraction
from suvix.contracts import (
    EvidenceRef,
    ExecutionMetadata,
    ExtractionResult,
    UsageReport,
    ValidationIssue,
    ValidationReport,
)
from suvix.evaluation import metrics


def _result(
    *,
    valid: bool = True,
    issues: list[ValidationIssue] | None = None,
    evidence: list[EvidenceRef] | None = None,
    latency: float = 1.0,
    provider_requests: int = 1,
) -> ExtractionResult:
    return ExtractionResult(
        data={},
        evidence=evidence or [],
        validation=ValidationReport(valid=valid, issues=issues or []),
        usage=UsageReport(latency_seconds=latency, provider_requests=provider_requests),
        execution=ExecutionMetadata(
            strategy="native_video",
            strategy_reason="test",
            provider="fake",
            model="fake-1",
        ),
    )


# ---------------------------------------------------------------------------
# Structural metrics
# ---------------------------------------------------------------------------


class TestJsonParseSuccess:
    def test_parsed_data_counts_as_success(self):
        assert metrics.json_parse_success([ProviderExtraction(data={"a": 1})]) == 1.0

    def test_valid_json_text_counts_as_success(self):
        assert metrics.json_parse_success([ProviderExtraction(raw_text='{"a": 1}')]) == 1.0

    def test_malformed_text_counts_as_failure(self):
        assert metrics.json_parse_success([ProviderExtraction(raw_text="not json")]) == 0.0

    def test_non_object_json_counts_as_failure(self):
        # Suvix requires a JSON object, not an array or scalar.
        assert metrics.json_parse_success([ProviderExtraction(raw_text="[1, 2]")]) == 0.0
        assert metrics.json_parse_success([ProviderExtraction(raw_text='"str"')]) == 0.0

    def test_neither_data_nor_text_counts_as_failure(self):
        assert metrics.json_parse_success([ProviderExtraction()]) == 0.0

    def test_mixed_rate(self):
        extractions = [
            ProviderExtraction(data={"a": 1}),
            ProviderExtraction(raw_text="bad"),
            ProviderExtraction(raw_text='{"b": 2}'),
            ProviderExtraction(),
        ]
        assert metrics.json_parse_success(extractions) == pytest.approx(0.5)

    def test_empty_is_undefined(self):
        assert metrics.json_parse_success([]) is None


class TestSchemaPassRate:
    def test_all_pass(self):
        assert metrics.schema_pass_rate([_result(), _result()]) == 1.0

    def test_half_pass(self):
        assert metrics.schema_pass_rate([_result(valid=True), _result(valid=False)]) == 0.5

    def test_empty_is_undefined(self):
        assert metrics.schema_pass_rate([]) is None


class TestMissingRequiredFieldRate:
    def _required_issue(self) -> ValidationIssue:
        return ValidationIssue(
            code="schema_violation",
            message="'events' is a required property",
            field="/",
        )

    def test_detects_required_property_message(self):
        bad = _result(valid=False, issues=[self._required_issue()])
        assert metrics.missing_required_field_rate([bad, _result()]) == 0.5

    def test_other_violations_do_not_count(self):
        other = _result(
            valid=False,
            issues=[
                ValidationIssue(
                    code="schema_violation",
                    message="3 is not of type 'string'",
                    field="/events/0/type",
                )
            ],
        )
        assert metrics.missing_required_field_rate([other]) == 0.0

    def test_empty_is_undefined(self):
        assert metrics.missing_required_field_rate([]) is None


class TestInvalidEvidenceRate:
    def test_frame_without_id_is_invalid(self):
        bad = _result(evidence=[EvidenceRef(ref_type="frame")])
        good = _result(evidence=[EvidenceRef(ref_type="frame", frame_id="f1")])
        assert metrics.invalid_evidence_rate([bad, good]) == 0.5

    def test_segment_needs_both_bounds(self):
        bad = _result(evidence=[EvidenceRef(ref_type="segment", start_seconds=1.0)])
        good = _result(
            evidence=[EvidenceRef(ref_type="segment", start_seconds=1.0, end_seconds=2.0)]
        )
        assert metrics.invalid_evidence_rate([bad, good]) == 0.5

    def test_provider_reported_needs_nothing(self):
        ok = _result(evidence=[EvidenceRef(ref_type="provider_reported")])
        assert metrics.invalid_evidence_rate([ok]) == 0.0

    def test_empty_is_undefined(self):
        assert metrics.invalid_evidence_rate([]) is None


# ---------------------------------------------------------------------------
# Semantic metrics
# ---------------------------------------------------------------------------


class TestEventPrecisionRecallF1:
    def test_perfect_match(self):
        pred = [
            {"type": "flash", "timestamp_seconds": 2.5},
            {"type": "flash", "timestamp_seconds": 5.5},
        ]
        assert metrics.event_precision_recall_f1(
            pred, pred, time_tolerance_s=1.0
        ) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    def test_extra_prediction(self):
        pred = [
            {"type": "flash", "timestamp_seconds": 2.5},
            {"type": "flash", "timestamp_seconds": 50.0},
        ]
        exp = [{"type": "flash", "timestamp_seconds": 2.5}]
        out = metrics.event_precision_recall_f1(pred, exp, time_tolerance_s=1.0)
        assert out["precision"] == pytest.approx(0.5)
        assert out["recall"] == pytest.approx(1.0)
        assert out["f1"] == pytest.approx(2 * 0.5 * 1.0 / 1.5)

    def test_type_mismatch_does_not_match(self):
        pred = [{"type": "beep", "timestamp_seconds": 2.5}]
        exp = [{"type": "flash", "timestamp_seconds": 2.5}]
        out = metrics.event_precision_recall_f1(pred, exp, time_tolerance_s=1.0)
        assert out == {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    def test_tolerance_boundary(self):
        pred = [{"type": "flash", "timestamp_seconds": 11.0}]
        exp = [{"type": "flash", "timestamp_seconds": 10.0}]
        in_tol = metrics.event_precision_recall_f1(pred, exp, time_tolerance_s=1.0)
        assert in_tol["recall"] == 1.0  # |11.0 - 10.0| == 1.0 <= tol
        out_tol = metrics.event_precision_recall_f1(pred, exp, time_tolerance_s=0.5)
        assert out_tol["recall"] == 0.0

    def test_greedy_picks_closest(self):
        # Two predictions could match; the closest one wins the match.
        pred = [
            {"type": "flash", "timestamp_seconds": 10.4},
            {"type": "flash", "timestamp_seconds": 10.1},
        ]
        exp = [{"type": "flash", "timestamp_seconds": 10.0}]
        out = metrics.event_precision_recall_f1(pred, exp, time_tolerance_s=1.0)
        assert out["precision"] == pytest.approx(0.5)
        assert out["recall"] == pytest.approx(1.0)

    def test_unmatchable_events_are_missed(self):
        pred = [{"no_type": "flash"}]
        exp = [{"type": "flash", "timestamp_seconds": 2.5}]
        out = metrics.event_precision_recall_f1(pred, exp, time_tolerance_s=1.0)
        assert out == {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    def test_empty_predicted(self):
        out = metrics.event_precision_recall_f1(
            [], [{"type": "flash", "timestamp_seconds": 1.0}], time_tolerance_s=1.0
        )
        assert out["precision"] is None
        assert out["recall"] == 0.0
        assert out["f1"] is None

    def test_empty_expected(self):
        out = metrics.event_precision_recall_f1(
            [{"type": "flash", "timestamp_seconds": 1.0}], [], time_tolerance_s=1.0
        )
        assert out["precision"] == 0.0
        assert out["recall"] is None
        assert out["f1"] is None


class TestCountAccuracy:
    def test_exact(self):
        assert metrics.count_accuracy(3, 3) == 1.0

    def test_off_by_one_is_zero(self):
        # Binary accuracy: there is no partial credit for being close.
        assert metrics.count_accuracy(2, 3) == 0.0


class TestTextExactAccuracy:
    def test_normalized_match(self):
        assert metrics.text_exact_accuracy("SCORE  3-1 ", "score 3-1") == 1.0

    def test_different_text(self):
        assert metrics.text_exact_accuracy("SCORE 3-1", "SCORE 2-1") == 0.0


class TestTimestampMae:
    def test_hand_computed(self):
        pred = [10.4, 20.0]
        exp = [10.0, 21.0]
        # Pairs (10.4, 10.0) and (20.0, 21.0): (0.4 + 1.0) / 2 = 0.7
        assert metrics.timestamp_mae(pred, exp, time_tolerance_s=2.0) == pytest.approx(0.7)

    def test_no_match_is_undefined(self):
        assert metrics.timestamp_mae([100.0], [1.0], time_tolerance_s=1.0) is None

    def test_empty_is_undefined(self):
        assert metrics.timestamp_mae([], [1.0], time_tolerance_s=1.0) is None


class TestDuplicateEventRate:
    def test_second_match_of_same_event_is_duplicate(self):
        pred = [
            {"type": "flash", "timestamp_seconds": 10.1},
            {"type": "flash", "timestamp_seconds": 10.4},
        ]
        exp = [{"type": "flash", "timestamp_seconds": 10.0}]
        # Both predictions match the same expected event: 1 duplicate of 2.
        assert metrics.duplicate_event_rate(pred, exp, time_tolerance_s=1.0) == pytest.approx(
            0.5
        )

    def test_no_duplicates(self):
        pred = [{"type": "flash", "timestamp_seconds": 10.1}]
        exp = [{"type": "flash", "timestamp_seconds": 10.0}]
        assert metrics.duplicate_event_rate(pred, exp, time_tolerance_s=1.0) == 0.0

    def test_empty_predicted_is_undefined(self):
        assert (
            metrics.duplicate_event_rate([], [{"type": "f", "timestamp_seconds": 1.0}],
                                         time_tolerance_s=1.0)
            is None
        )


class TestUnsupportedClaimRate:
    def test_unmatched_predictions(self):
        pred = [
            {"type": "flash", "timestamp_seconds": 2.5},
            {"type": "flash", "timestamp_seconds": 50.0},
        ]
        exp = [{"type": "flash", "timestamp_seconds": 2.5}]
        assert metrics.unsupported_claim_rate(pred, exp, time_tolerance_s=1.0) == pytest.approx(
            0.5
        )

    def test_all_supported(self):
        pred = [{"type": "flash", "timestamp_seconds": 2.5}]
        assert (
            metrics.unsupported_claim_rate(
                pred, pred, time_tolerance_s=1.0
            )
            == 0.0
        )

    def test_empty_predicted_is_undefined(self):
        assert (
            metrics.unsupported_claim_rate([], [{"type": "f", "timestamp_seconds": 1.0}],
                                           time_tolerance_s=1.0)
            is None
        )


# ---------------------------------------------------------------------------
# Operational metrics
# ---------------------------------------------------------------------------


class TestOperational:
    def test_mean_latency(self):
        assert metrics.mean_latency([1.0, 2.0, 3.0]) == pytest.approx(2.0)

    def test_mean_latency_empty_is_undefined(self):
        assert metrics.mean_latency([]) is None

    def test_total_provider_requests(self):
        assert metrics.total_provider_requests([2, 3, 0]) == 5

    def test_total_provider_requests_empty(self):
        assert metrics.total_provider_requests([]) == 0

    def test_failure_rate(self):
        assert metrics.failure_rate([True, False, True]) == pytest.approx(2 / 3)

    def test_failure_rate_empty_is_undefined(self):
        assert metrics.failure_rate([]) is None


# ---------------------------------------------------------------------------
# Economic metrics
# ---------------------------------------------------------------------------


class TestEconomic:
    def test_total_estimated_cost_sums_known(self):
        assert metrics.total_estimated_cost([1.5, None, 2.5]) == pytest.approx(4.0)

    def test_total_estimated_cost_all_unknown_is_undefined(self):
        assert metrics.total_estimated_cost([None, None]) is None

    def test_total_estimated_cost_empty_is_undefined(self):
        assert metrics.total_estimated_cost([]) is None

    def test_cost_per_correct_event(self):
        assert metrics.cost_per_correct_event(4.0, 2) == pytest.approx(2.0)

    def test_cost_per_correct_event_unknown_cost(self):
        assert metrics.cost_per_correct_event(None, 2) is None

    def test_cost_per_correct_event_zero_correct_is_undefined(self):
        # Division by zero would be a lie; undefined instead.
        assert metrics.cost_per_correct_event(4.0, 0) is None
