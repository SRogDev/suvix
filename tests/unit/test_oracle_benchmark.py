"""Oracle benchmark tests: prove the benchmark machinery tells the truth.

A test-local *oracle* adapter returns a task's expected output verbatim
(perfect prediction) or with a controlled, known distortion. The metrics
and the runner must then recover exactly the known values — precision /
recall / F1, MAE, signed timestamp bias, duplicate rate, schema pass rate.

This is offline pipeline validation only. It says nothing about any real
provider's accuracy: the oracle reads the answer key by construction.
Every expectation below is hand-computed from the distortion applied.

Also included: a greedy-vs-optimal matching divergence case. Greedy
matching (the implementation in ``suvix.evaluation.metrics``) is compared
against a brute-force optimal assignment computed inside the test.
"""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.evaluation import metrics
from suvix.evaluation.runner import BenchmarkTask, run_baseline, summarize

TASKS_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "tasks"


def load_task(task_id: str) -> BenchmarkTask:
    return BenchmarkTask(**json.loads((TASKS_DIR / f"{task_id}.json").read_text()))


def load_all_tasks() -> list[BenchmarkTask]:
    return [
        BenchmarkTask(**json.loads(p.read_text()))
        for p in sorted(TASKS_DIR.glob("*.json"))
    ]


class OracleExtractor:
    """Deterministic adapter that returns fixed data verbatim.

    Implements the :class:`VideoExtractor` protocol directly (not the
    scripted fake): the data is derived from a task's ``expected`` block,
    optionally distorted by the test before construction.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._capabilities = ExtractorCapabilities(
            provider="oracle",
            model="oracle-1",
            native_video=True,
            image_input=True,
            multi_image=True,
            structured_output=True,
            usage_metadata=True,
            timestamp_support=True,
            notes="Test-local oracle; returns the answer key, not a provider.",
        )
        self.calls: list[AdapterRequest] = []

    @property
    def name(self) -> str:
        return "oracle/oracle-1"

    @property
    def capabilities(self) -> ExtractorCapabilities:
        return self._capabilities

    async def extract(self, request: AdapterRequest) -> ProviderExtraction:
        self.calls.append(request)
        return ProviderExtraction(data=copy.deepcopy(self._data))


assert isinstance(OracleExtractor({}), VideoExtractor)  # protocol conformance


def oracle_data(task: BenchmarkTask, transform: Any = None) -> dict[str, Any]:
    """Build the data an oracle returns for ``task`` from its expected block."""
    if task.category == "visible_text":
        # Runner convention: expected texts are nested, predicted data is flat.
        data: dict[str, Any] = dict(task.expected["texts"])
    else:
        data = copy.deepcopy(task.expected)
    if transform is not None:
        data = transform(data)
    return data


async def run_oracle(
    task: BenchmarkTask,
    data: dict[str, Any],
    tmp_path: Path,
    baseline: str = "A_direct_native",
) -> Any:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    task = task.model_copy(update={"video_path": str(video)})

    def factory(name: str) -> VideoExtractor:
        return OracleExtractor(data)

    return await run_baseline(task, baseline, extractor_factory=factory)


# ---------------------------------------------------------------------------
# New synthetic fixtures (tasks load, expectations from generation params)
# ---------------------------------------------------------------------------


class TestNewFixtureTasks:
    def test_all_tasks_load_and_new_ids_present(self):
        ids = {t.task_id for t in load_all_tasks()}
        assert {
            "temporal_flashes",
            "objects_counts",
            "visible_text",
            "changing_counts",
            "changing_text",
            "rapid_events",
            "negative_control",
        } <= ids

    def test_changing_counts_expectation(self):
        task = load_task("changing_counts")
        assert task.category == "objects_counts"
        # Generation parameters: 2 squares 0-4s, 4 squares 4-8s.
        assert task.expected["counts"] == {
            "squares_first_half": 2,
            "squares_second_half": 4,
        }

    def test_changing_text_expectation(self):
        task = load_task("changing_text")
        # "ALPHA" 0-4s -> midpoint 2.0; "BRAVO" 4-8s -> midpoint 6.0.
        assert task.expected["events"] == [
            {"type": "text_alpha", "timestamp_seconds": 2.0},
            {"type": "text_bravo", "timestamp_seconds": 6.0},
        ]

    def test_rapid_events_expectation(self):
        task = load_task("rapid_events")
        events = task.expected["events"]
        # 0.3s flashes starting at 1..6s -> midpoints 1.15, 2.15, ..., 6.15.
        assert [e["timestamp_seconds"] for e in events] == [
            1.15, 2.15, 3.15, 4.15, 5.15, 6.15,
        ]
        assert all(e["type"] == "flash" for e in events)
        # ~1s spacing must not be blurred by a 1s tolerance window.
        assert task.time_tolerance_seconds <= 0.5

    def test_negative_control_expectation(self):
        task = load_task("negative_control")
        assert task.expected["events"] == []


# ---------------------------------------------------------------------------
# Perfect oracle: the machinery must report perfection exactly
# ---------------------------------------------------------------------------


class TestPerfectOracle:
    async def test_temporal_events_perfect_scores(self, tmp_path):
        task = load_task("temporal_flashes")
        result = await run_oracle(task, oracle_data(task), tmp_path)
        assert result.error is None
        assert result.metrics["event_precision"] == 1.0
        assert result.metrics["event_recall"] == 1.0
        assert result.metrics["event_f1"] == 1.0
        assert result.metrics["timestamp_mae"] == 0.0
        assert result.metrics["timestamp_bias"] == 0.0
        assert result.metrics["duplicate_event_rate"] == 0.0
        assert result.metrics["unsupported_claim_rate"] == 0.0
        assert result.metrics["schema_pass"] == 1.0
        assert metrics.schema_pass_rate([result.result]) == 1.0

    async def test_perfect_oracle_through_suvix_baseline_b(self, tmp_path):
        # Runner-level smoke test through full Suvix orchestration.
        task = load_task("temporal_flashes")
        result = await run_oracle(
            task, oracle_data(task), tmp_path, baseline="B_suvix_native"
        )
        assert result.error is None
        assert result.metrics["event_f1"] == 1.0
        assert result.metrics["timestamp_bias"] == 0.0
        assert result.metrics["schema_pass"] == 1.0

    async def test_changing_counts_perfect_scores(self, tmp_path):
        task = load_task("changing_counts")
        result = await run_oracle(task, oracle_data(task), tmp_path)
        assert result.error is None
        assert result.metrics["count_accuracy_mean"] == 1.0
        assert result.metrics["count_labels_exact"] == 2
        assert result.metrics["schema_pass"] == 1.0

    async def test_negative_control_perfect_is_honestly_undefined(self, tmp_path):
        task = load_task("negative_control")
        result = await run_oracle(task, oracle_data(task), tmp_path)
        assert result.error is None
        assert result.metrics["schema_pass"] == 1.0
        # No predictions and no expectations: P/R/F1 denominators are zero,
        # so the rates stay undefined (None) rather than faking a 1.0.
        assert result.metrics["event_precision"] is None
        assert result.metrics["event_recall"] is None
        assert result.metrics["event_f1"] is None


# ---------------------------------------------------------------------------
# Controlled noise: the machinery must recover exactly the known values
# ---------------------------------------------------------------------------


class TestControlledNoise:
    async def test_timestamp_jitter_plus_0_3(self, tmp_path):
        task = load_task("temporal_flashes")

        def jitter(data: dict[str, Any]) -> dict[str, Any]:
            for event in data["events"]:
                event["timestamp_seconds"] += 0.3
            return data

        result = await run_oracle(task, oracle_data(task, jitter), tmp_path)
        # +0.3s is within the 1.0s tolerance: everything still matches, and
        # both MAE and signed bias must recover exactly +0.3.
        assert result.metrics["event_f1"] == 1.0
        assert result.metrics["timestamp_mae"] == pytest.approx(0.3)
        assert result.metrics["timestamp_bias"] == pytest.approx(0.3)

    async def test_drop_every_second_event(self, tmp_path):
        task = load_task("rapid_events")

        def drop(data: dict[str, Any]) -> dict[str, Any]:
            data["events"] = data["events"][::2]
            return data

        result = await run_oracle(task, oracle_data(task, drop), tmp_path)
        # 3 of 6 events remain, all correct: recall 0.5, precision 1.0.
        assert result.metrics["event_recall"] == pytest.approx(0.5)
        assert result.metrics["event_precision"] == 1.0

    async def test_duplicate_every_event(self, tmp_path):
        task = load_task("temporal_flashes")

        def duplicate(data: dict[str, Any]) -> dict[str, Any]:
            data["events"] = [e for e in data["events"] for _ in range(2)]
            return data

        result = await run_oracle(task, oracle_data(task, duplicate), tmp_path)
        # 4 predictions, 2 matched: precision 0.5. Each expected event is
        # reported twice: 2 duplicates / 4 predictions = 0.5.
        assert result.metrics["event_precision"] == pytest.approx(0.5)
        assert result.metrics["event_recall"] == 1.0
        assert result.metrics["duplicate_event_rate"] == pytest.approx(0.5)

    async def test_two_hallucinated_events(self, tmp_path):
        task = load_task("temporal_flashes")

        def hallucinate(data: dict[str, Any]) -> dict[str, Any]:
            data["events"] += [
                {"type": "flash", "timestamp_seconds": 20.0},
                {"type": "flash", "timestamp_seconds": 30.0},
            ]
            return data

        result = await run_oracle(task, oracle_data(task, hallucinate), tmp_path)
        # 2 correct of 4 predicted: precision exactly 2/4.
        assert result.metrics["event_precision"] == pytest.approx(0.5)
        assert result.metrics["event_recall"] == 1.0
        assert result.metrics["unsupported_claim_rate"] == pytest.approx(0.5)

    async def test_hallucinations_on_negative_control(self, tmp_path):
        task = load_task("negative_control")
        data = {
            "events": [
                {"type": "flash", "timestamp_seconds": 1.0},
                {"type": "flash", "timestamp_seconds": 2.0},
            ]
        }
        result = await run_oracle(task, data, tmp_path)
        # Nothing was there: every prediction is a false positive.
        assert result.metrics["event_precision"] == 0.0
        assert result.metrics["unsupported_claim_rate"] == 1.0

    async def test_missing_required_field_halves_schema_pass_rate(self, tmp_path):
        task = load_task("temporal_flashes")
        perfect = await run_oracle(task, oracle_data(task), tmp_path)
        # Remove the schema-required "events" field entirely.
        missing = await run_oracle(task, {}, tmp_path)
        assert perfect.metrics["schema_pass"] == 1.0
        assert missing.metrics["schema_pass"] == 0.0
        assert metrics.schema_pass_rate(
            [perfect.result, missing.result]
        ) == pytest.approx(0.5)
        summary = summarize([perfect, missing])
        mean = summary["A_direct_native"]["metric_means"]["schema_pass"]
        assert mean == {"n": 2, "mean": pytest.approx(0.5)}


# ---------------------------------------------------------------------------
# Greedy vs optimal matching: a measured, documented divergence
# ---------------------------------------------------------------------------


def _optimal_match_count(
    predicted: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    time_tolerance_s: float,
) -> int:
    """Brute-force optimal assignment: max matched pairs over all bijections."""
    best = 0
    n, m = len(predicted), len(expected)
    # Assign each item on the shorter side to a distinct item on the longer.
    if n <= m:
        assignments = (
            zip(predicted, (expected[j] for j in perm), strict=True)
            for perm in itertools.permutations(range(m), n)
        )
    else:
        assignments = (
            zip((predicted[i] for i in perm), expected, strict=True)
            for perm in itertools.permutations(range(n), m)
        )
    for pairs in assignments:
        matched = sum(
            1
            for p, e in pairs
            if p["type"] == e["type"]
            and abs(p["timestamp_seconds"] - e["timestamp_seconds"])
            <= time_tolerance_s
        )
        best = max(best, matched)
    return best


class TestGreedyVsOptimal:
    def test_greedy_provably_underperforms_optimal(self):
        # Pred A (0.5) can match exp X (0.0, diff 0.5) or Y (1.1, diff 0.6).
        # Pred B (-0.6) can match only X (diff 0.6); B-Y is 1.7 > tolerance.
        # Greedy takes the single closest pair A-X first, which blocks both
        # remaining candidates -> 1 match. Optimal (A-Y, B-X) -> 2 matches.
        predicted = [
            {"type": "flash", "timestamp_seconds": 0.5},
            {"type": "flash", "timestamp_seconds": -0.6},
        ]
        expected = [
            {"type": "flash", "timestamp_seconds": 0.0},
            {"type": "flash", "timestamp_seconds": 1.1},
        ]
        tol = 1.0
        out = metrics.event_precision_recall_f1(
            predicted, expected, time_tolerance_s=tol
        )
        greedy_matched = round(out["recall"] * len(expected))
        optimal_matched = _optimal_match_count(
            predicted, expected, time_tolerance_s=tol
        )
        assert greedy_matched == 1
        assert optimal_matched == 2
        assert out["recall"] == pytest.approx(0.5)  # greedy
        assert optimal_matched / len(expected) == 1.0  # optimal recall
