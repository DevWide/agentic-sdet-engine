"""Tests for the evaluation harness. The aggregation logic is pure, so no LLM is involved."""

from pathlib import Path

import pytest

from agentic_sdet.evaluation.runner import SpecResult, categorize, percentile, summarize
from agentic_sdet.telemetry.cost import Usage, estimate_cost, usage_from_message


def make(name, category, expectation, passed, heals, duration=1.0, **kw):
    return SpecResult(
        name=name,
        category=category,
        expectation=expectation,
        passed=passed,
        healing_attempts=heals,
        duration_s=duration,
        **kw,
    )


class TestOutcomeClassification:
    def test_pass_without_healing_is_first_try(self):
        r = make("a", "easy", "pass_first_try", True, 0)
        assert r.outcome == "pass_first_try"
        assert r.first_pass is True
        assert r.as_expected is True

    def test_pass_with_healing_is_not_first_try(self):
        r = make("b", "heal", "pass_after_healing", True, 2)
        assert r.outcome == "pass_after_healing"
        assert r.first_pass is False
        assert r.as_expected is True

    def test_impossible_spec_failing_counts_as_expected(self):
        # The engine giving up is the designed behaviour here, not a defect.
        r = make("c", "impossible", "give_up", False, 3)
        assert r.outcome == "give_up"
        assert r.as_expected is True

    def test_easy_spec_that_needed_healing_is_a_miss(self):
        r = make("d", "easy", "pass_first_try", True, 1)
        assert r.as_expected is False

    def test_crash_outranks_every_other_outcome(self):
        r = make("e", "easy", "pass_first_try", False, 0, crashed="RateLimitError: 429")
        assert r.outcome == "crashed"
        assert r.as_expected is False


class TestSummary:
    @pytest.fixture
    def results(self):
        return [
            make("e1", "easy", "pass_first_try", True, 0, 2.0, cost_usd=0.001, llm_calls=1),
            make("e2", "easy", "pass_first_try", True, 0, 3.0, cost_usd=0.001, llm_calls=1),
            make("h1", "heal", "pass_after_healing", True, 1, 6.0, cost_usd=0.003, llm_calls=2),
            make(
                "h2",
                "heal",
                "pass_after_healing",
                False,
                3,
                12.0,
                cost_usd=0.008,
                llm_calls=4,
                error_type="AssertionError",
            ),
            make(
                "i1",
                "impossible",
                "give_up",
                False,
                3,
                11.0,
                cost_usd=0.007,
                llm_calls=4,
                error_type="CollectionError",
            ),
        ]

    def test_headline_rates(self, results):
        s = summarize(results)
        assert s.total == 5
        assert s.passed == 3
        assert s.first_pass == 2
        assert s.pass_rate == pytest.approx(0.6)
        assert s.first_pass_rate == pytest.approx(0.4)

    def test_expectation_rate_ignores_pass_fail(self, results):
        # h2 is the only miss: it was supposed to heal and instead gave up.
        s = summarize(results)
        assert s.as_expected == 4
        assert s.expectation_rate == pytest.approx(0.8)

    def test_healing_recovery_counts_only_runs_that_needed_healing(self, results):
        s = summarize(results)
        assert s.healed == 1
        assert s.gave_up == 2
        assert s.healing_recovery_rate == pytest.approx(1 / 3)

    def test_cost_and_tokens_are_summed(self, results):
        s = summarize(results)
        assert s.total_cost_usd == pytest.approx(0.020)
        assert s.avg_cost_usd == pytest.approx(0.004)
        assert s.llm_calls == 12

    def test_failure_modes_are_ranked(self, results):
        s = summarize(results)
        assert s.failure_modes == {"AssertionError": 1, "CollectionError": 1}

    def test_by_category_breakdown(self, results):
        s = summarize(results)
        assert s.by_category["easy"] == {"total": 2, "as_expected": 2}
        assert s.by_category["heal"] == {"total": 2, "as_expected": 1}

    def test_empty_corpus_does_not_divide_by_zero(self):
        s = summarize([])
        assert s.pass_rate == 0.0
        assert s.expectation_rate == 0.0
        assert s.healing_recovery_rate == 0.0
        assert s.avg_cost_usd == 0.0


class TestPercentile:
    def test_p50_and_p95(self):
        values = list(range(1, 101))
        assert percentile(values, 50) == 50
        assert percentile(values, 95) == 95

    def test_single_value(self):
        assert percentile([4.2], 95) == 4.2

    def test_empty(self):
        assert percentile([], 95) == 0.0


class TestCategorize:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("easy_01_fizzbuzz.txt", "easy"),
            ("heal_05_rounding.txt", "heal"),
            ("impossible_02_contradiction.txt", "impossible"),
        ],
    )
    def test_prefix_becomes_category(self, filename, expected):
        assert categorize(Path(filename)) == expected


class TestCost:
    def test_known_model_is_priced(self):
        cost, priced = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert priced is True
        assert cost == pytest.approx(0.75)

    def test_dated_model_id_falls_back_to_base_name(self):
        cost, priced = estimate_cost("gpt-4o-mini-2024-07-18", 1_000_000, 0)
        assert priced is True
        assert cost == pytest.approx(0.15)

    def test_unknown_model_is_flagged_not_silently_zero(self):
        cost, priced = estimate_cost("some-local-llama", 1000, 1000)
        assert cost == 0.0
        assert priced is False

    def test_usage_adds_up(self):
        total = Usage(10, 5, 0.001) + Usage(20, 7, 0.002)
        assert total.input_tokens == 30
        assert total.output_tokens == 12
        assert total.total_tokens == 42
        assert total.cost_usd == pytest.approx(0.003)

    def test_missing_usage_metadata_is_tolerated(self):
        usage = usage_from_message(None, "gpt-4o-mini")
        assert usage.total_tokens == 0
        assert usage.cost_usd == 0.0
