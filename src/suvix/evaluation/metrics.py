"""Evaluation metrics for SUVIX_PLAN.md §16.4.

All functions are pure and deterministic: no network, no randomness, no
provider calls. Every function documents its formula and its limitations.

Conventions:

- Rates return ``float | None``: ``None`` means the metric is undefined for
  the input (e.g. empty denominator). ``None`` is never silently treated as
  zero — undefined stays undefined.
- Events are dicts with ``"type"`` (str) and ``"timestamp_seconds"``
  (numeric). Events missing either key cannot be matched: predicted ones are
  counted as unsupported claims, expected ones as misses.
- Matching is greedy: candidate pairs (same type, ``|t_pred - t_exp| <=
  tolerance``) are sorted by absolute time difference and consumed in order,
  each predicted and each expected event matched at most once.
"""

from __future__ import annotations

import json
import re
from typing import Any

from suvix.adapters.base import ProviderExtraction
from suvix.contracts import ExtractionResult

_MISSING_REQUIRED_RE = re.compile(r"is a required property")


def _event_key(event: dict[str, Any]) -> tuple[str, float] | None:
    """Return ``(type, timestamp)`` or ``None`` when the event is unmatchable."""
    event_type = event.get("type")
    timestamp = event.get("timestamp_seconds")
    if not isinstance(event_type, str):
        return None
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    return event_type, float(timestamp)


def _match_events(
    predicted: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    time_tolerance_s: float,
) -> list[tuple[int, int, float]]:
    """Greedy (type, timestamp) matching.

    Returns ``(pred_index, exp_index, abs_time_diff)`` triples. Each predicted
    and each expected event is used at most once; pairs are taken in order of
    increasing time difference.
    """
    candidates: list[tuple[float, int, int]] = []
    pred_keys = [_event_key(e) for e in predicted]
    exp_keys = [_event_key(e) for e in expected]
    for i, pkey in enumerate(pred_keys):
        if pkey is None:
            continue
        for j, ekey in enumerate(exp_keys):
            if ekey is None:
                continue
            ptype, pts = pkey
            etype, ets = ekey
            if ptype != etype:
                continue
            diff = abs(pts - ets)
            if diff <= time_tolerance_s:
                candidates.append((diff, i, j))
    candidates.sort()
    used_pred: set[int] = set()
    used_exp: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for diff, i, j in candidates:
        if i in used_pred or j in used_exp:
            continue
        used_pred.add(i)
        used_exp.add(j)
        pairs.append((i, j, diff))
    return pairs


# ---------------------------------------------------------------------------
# Structural quality (§16.4)
# ---------------------------------------------------------------------------


def _parses_as_json_object(extraction: ProviderExtraction) -> bool:
    if extraction.data is not None:
        return isinstance(extraction.data, dict)
    if extraction.raw_text:
        try:
            return isinstance(json.loads(extraction.raw_text), dict)
        except (json.JSONDecodeError, ValueError):
            return False
    return False


def json_parse_success(extractions: list[ProviderExtraction]) -> float | None:
    """Fraction of provider outcomes that yielded a JSON object.

    Formula: successes / attempts, where a success is either parsed ``data``
    (a dict) or ``raw_text`` that parses as a JSON object. Non-object JSON
    (arrays, scalars) counts as failure: Suvix requires an object matching
    the developer's schema.

    Limitation: a parseable object says nothing about whether the object is
    correct — that is what the semantic metrics are for.
    """
    if not extractions:
        return None
    successes = sum(1 for e in extractions if _parses_as_json_object(e))
    return successes / len(extractions)


def schema_pass_rate(results: list[ExtractionResult]) -> float | None:
    """Fraction of results whose local validation report is ``valid``.

    Formula: results with ``validation.valid`` / total results.

    Limitation: schema validity is structural, not semantic — a result can
    pass validation while containing hallucinated values.
    """
    if not results:
        return None
    passed = sum(1 for r in results if r.validation.valid)
    return passed / len(results)


def missing_required_field_rate(results: list[ExtractionResult]) -> float | None:
    """Fraction of results missing at least one schema-required field.

    Formula: results with >= 1 validation issue whose message matches
    ``"is a required property"`` (jsonschema's phrasing) / total results.

    Limitation: this is a heuristic over issue messages, not a structured
    issue code — it depends on the jsonschema library's wording.
    """
    if not results:
        return None

    def _missing(result: ExtractionResult) -> bool:
        return any(
            _MISSING_REQUIRED_RE.search(issue.message) for issue in result.validation.issues
        )

    return sum(1 for r in results if _missing(r)) / len(results)


def _evidence_is_invalid(ref: Any) -> bool:
    ref_type = ref.ref_type
    if ref_type == "frame":
        return not ref.frame_id
    if ref_type == "segment":
        return ref.start_seconds is None or ref.end_seconds is None
    # "provider_reported" and "description" carry no structural requirements.
    return False


def invalid_evidence_rate(results: list[ExtractionResult]) -> float | None:
    """Fraction of results carrying at least one structurally invalid evidence ref.

    Formula: results with >= 1 evidence ref where a ``frame`` ref lacks
    ``frame_id`` or a ``segment`` ref lacks ``start_seconds``/``end_seconds``
    / total results.

    Limitation: structural only — it cannot detect a timestamp that is
    plausible but wrong, or a frame_id that points at the wrong frame.
    """
    if not results:
        return None
    invalid = sum(1 for r in results if any(_evidence_is_invalid(e) for e in r.evidence))
    return invalid / len(results)


# ---------------------------------------------------------------------------
# Semantic quality (§16.4)
# ---------------------------------------------------------------------------


def event_precision_recall_f1(
    predicted_events: list[dict[str, Any]],
    expected_events: list[dict[str, Any]],
    *,
    time_tolerance_s: float,
) -> dict[str, float | None]:
    """Event-level precision/recall/F1 under greedy (type, timestamp) matching.

    Formulas: precision = matched / predicted, recall = matched / expected,
    f1 = 2·P·R / (P + R), or 0.0 when both sides are defined but nothing
    matched. Each side is ``None`` when its denominator is zero; f1 is
    ``None`` when either side is ``None``.

    Limitations: greedy matching is an approximation, not an optimal
    assignment; the tolerance is a free parameter and results must be
    reported together with it; event identity is reduced to (type,
    timestamp) — argument-level differences are invisible.
    """
    pairs = _match_events(predicted_events, expected_events, time_tolerance_s=time_tolerance_s)
    matched = len(pairs)
    precision = matched / len(predicted_events) if predicted_events else None
    recall = matched / len(expected_events) if expected_events else None
    f1: float | None = None
    if precision is not None and recall is not None:
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
    return {"precision": precision, "recall": recall, "f1": f1}


def count_accuracy(predicted: int | None, expected: int) -> float:
    """Binary object-count accuracy: 1.0 on exact match, 0.0 otherwise.

    ``predicted`` may be ``None`` when the extraction produced no count
    for the label — a missing count is simply not an exact match (0.0).

    Limitation: deliberately no partial credit — an off-by-one counts the
    same as a wild miss. Use a separate error-magnitude metric if the
    difference matters for the task.
    """
    return 1.0 if predicted == expected else 0.0


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def text_exact_accuracy(predicted: str, expected: str) -> float:
    """1.0 when the texts match after normalization, else 0.0.

    Normalization: casefold + collapse all whitespace runs to single spaces +
    strip. Formula: 1.0 if normalized equal else 0.0.

    Limitation: binary — one wrong character scores the same as completely
    different text; OCR-style character error rates are out of scope.
    """
    return 1.0 if _normalize_text(predicted) == _normalize_text(expected) else 0.0


def timestamp_mae(
    predicted_times: list[float],
    expected_times: list[float],
    *,
    time_tolerance_s: float,
) -> float | None:
    """Mean absolute timestamp error over greedily matched pairs.

    Formula: mean(|t_pred - t_exp|) over the matched pairs (same greedy
    matching as events, without the type constraint). ``None`` when no pairs
    match.

    Limitation: unmatched timestamps are invisible — a result can have a
    great MAE while missing half the events. Always read alongside recall.
    """
    pred_events = [{"type": "t", "timestamp_seconds": t} for t in predicted_times]
    exp_events = [{"type": "t", "timestamp_seconds": t} for t in expected_times]
    pairs = _match_events(pred_events, exp_events, time_tolerance_s=time_tolerance_s)
    if not pairs:
        return None
    return sum(diff for _, _, diff in pairs) / len(pairs)


def duplicate_event_rate(
    predicted_events: list[dict[str, Any]],
    expected_events: list[dict[str, Any]],
    *,
    time_tolerance_s: float,
) -> float | None:
    """Fraction of predicted events that redundantly report an expected event.

    Formula: for each expected event, count the predicted events matching it
    (same type, within tolerance); each match beyond the first is a
    duplicate. Rate = duplicates / predicted_total, ``None`` when there are
    no predicted events.

    Limitation: a legitimate repeated event at nearly the same timestamp is
    indistinguishable from a duplicate — check ``known_ambiguities`` on the
    task when this rate looks suspicious.
    """
    if not predicted_events:
        return None
    duplicates = 0
    for exp in expected_events:
        ekey = _event_key(exp)
        if ekey is None:
            continue
        etype, ets = ekey
        matches = sum(
            1
            for pred in predicted_events
            if (pkey := _event_key(pred)) is not None
            and pkey[0] == etype
            and abs(pkey[1] - ets) <= time_tolerance_s
        )
        duplicates += max(0, matches - 1)
    return duplicates / len(predicted_events)


def unsupported_claim_rate(
    predicted_events: list[dict[str, Any]],
    expected_events: list[dict[str, Any]],
    *,
    time_tolerance_s: float,
) -> float | None:
    """Fraction of predicted events with no matching expected event (heuristic).

    Formula: unmatched_predicted / predicted_total under the same greedy
    matching as precision/recall, ``None`` when there are no predicted
    events. This is 1 − precision by construction, reported separately
    because the plan (§16.4) names it as its own metric.

    Limitation: "unsupported" is relative to the expected annotation, which
    may itself be incomplete — a high rate can mean bad predictions or an
    incomplete ground truth. See the task's ``evaluation_notes``.
    """
    if not predicted_events:
        return None
    pairs = _match_events(predicted_events, expected_events, time_tolerance_s=time_tolerance_s)
    matched_pred = {i for i, _, _ in pairs}
    unmatched = len(predicted_events) - len(matched_pred)
    return unmatched / len(predicted_events)


# ---------------------------------------------------------------------------
# Operational performance (§16.4)
# ---------------------------------------------------------------------------


def mean_latency(latencies: list[float]) -> float | None:
    """Arithmetic mean of end-to-end latencies in seconds.

    ``None`` for an empty input. Wall-clock latency only — it includes
    provider time, local validation, and recovery; it is not a pure model
    latency figure.
    """
    if not latencies:
        return None
    return sum(latencies) / len(latencies)


def total_provider_requests(request_counts: list[int]) -> int:
    """Total provider requests across runs: sum of per-run counts.

    Recovery/repair calls are included in each run's count (Suvix records
    them in ``usage.provider_requests``) — the plan (§16.3) requires counting
    all additional model calls, so this sum must never exclude them.
    """
    return sum(request_counts)


def failure_rate(failed: list[bool]) -> float | None:
    """Fraction of runs that failed: failures / total, ``None`` when empty.

    A "failure" is whatever the caller defines (exception, unrecoverable
    output, timeout) — the flag list makes the definition explicit at the
    call site.
    """
    if not failed:
        return None
    return sum(1 for f in failed if f) / len(failed)


# ---------------------------------------------------------------------------
# Economic performance (§16.4)
# ---------------------------------------------------------------------------


def total_estimated_cost(costs: list[float | None]) -> float | None:
    """Sum of per-run estimated costs, ignoring unknown (``None``) entries.

    Returns ``None`` when no run has a known cost — an unknown total is not
    the same as a zero total. When some entries are unknown, the sum covers
    only the known ones; callers must label the figure as partial.

    Limitation: estimates are only as good as the pricing table and the
    usage metadata behind them (see :mod:`suvix.evaluation.cost`).
    """
    known = [c for c in costs if c is not None]
    if not known:
        return None
    return sum(known)


def cost_per_correct_event(
    total_cost_usd: float | None, correct_events: int
) -> float | None:
    """Cost efficiency: total cost divided by the number of correct events.

    ``None`` when the cost is unknown or when no events were correct
    (dividing by zero would fabricate a number). "Correct" is defined by the
    task's own criterion (e.g. matched events for temporal tasks).
    """
    if total_cost_usd is None or correct_events <= 0:
        return None
    return total_cost_usd / correct_events
