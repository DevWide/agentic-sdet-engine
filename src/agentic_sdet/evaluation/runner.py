"""Evaluation harness: run a corpus of specs and report how the engine actually behaves.

Each spec carries an expectation derived from its filename prefix, so the report answers
"did the engine do what it was designed to do?" rather than the weaker "did it pass?".
An `impossible_*` spec that fails is a success for the engine — it means the retry ceiling
held instead of the agent faking a green run.
"""

import math
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agentic_sdet.graph import build_sdet_graph
from agentic_sdet.telemetry.tracer import tracer

# Filename prefix -> what the engine is supposed to do with that spec.
EXPECTATIONS = {
    "easy": "pass_first_try",
    "heal": "pass_after_healing",
    "impossible": "give_up",
}


@dataclass
class SpecResult:
    name: str
    category: str
    expectation: str
    passed: bool
    healing_attempts: int
    duration_s: float
    error_type: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    crashed: Optional[str] = None

    @property
    def first_pass(self) -> bool:
        return self.passed and self.healing_attempts == 0

    @property
    def outcome(self) -> str:
        if self.crashed:
            return "crashed"
        if self.passed:
            return "pass_first_try" if self.healing_attempts == 0 else "pass_after_healing"
        return "give_up"

    @property
    def as_expected(self) -> bool:
        return self.outcome == self.expectation


@dataclass
class EvalSummary:
    total: int
    passed: int
    first_pass: int
    healed: int
    gave_up: int
    crashed: int
    as_expected: int
    avg_healing_attempts: float
    total_cost_usd: float
    total_tokens: int
    llm_calls: int
    p50_latency_s: float
    p95_latency_s: float
    failure_modes: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def first_pass_rate(self) -> float:
        return self.first_pass / self.total if self.total else 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def expectation_rate(self) -> float:
        return self.as_expected / self.total if self.total else 0.0

    @property
    def healing_recovery_rate(self) -> float:
        """Of the runs that failed on the first attempt, how many the healer rescued."""
        needed_healing = self.healed + self.gave_up
        return self.healed / needed_healing if needed_healing else 0.0

    @property
    def avg_cost_usd(self) -> float:
        return self.total_cost_usd / self.total if self.total else 0.0


def categorize(path: Path) -> str:
    return path.stem.split("_", 1)[0]


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile; enough for a corpus of this size."""
    if not values:
        return 0.0
    ordered = sorted(values)
    # ceil, not round: banker's rounding puts p95 of 1..100 at 96 instead of 95.
    rank = math.ceil(pct / 100 * len(ordered))
    index = max(0, min(len(ordered) - 1, rank - 1))
    return ordered[index]


def run_spec(path: Path) -> SpecResult:
    """Run one spec through the graph, isolated so a crash never aborts the corpus."""
    category = categorize(path)
    expectation = EXPECTATIONS.get(category, "pass_first_try")
    started = time.perf_counter()

    with tracer.start_as_current_span("sdet.eval_spec") as span:
        span.set_attribute("sdet.spec_file", path.name)
        span.set_attribute("sdet.eval_category", category)
        span.set_attribute("sdet.eval_expectation", expectation)
        try:
            final = build_sdet_graph().invoke(
                {
                    "spec_content": path.read_text(encoding="utf-8"),
                    "retry_count": 0,
                    "is_passing": False,
                }
            )
        except Exception as exc:  # noqa: BLE001 - one bad spec must not kill the run
            span.set_attribute("sdet.eval_crashed", True)
            return SpecResult(
                name=path.stem,
                category=category,
                expectation=expectation,
                passed=False,
                healing_attempts=0,
                duration_s=time.perf_counter() - started,
                crashed=f"{type(exc).__name__}: {exc}",
            )

        result = SpecResult(
            name=path.stem,
            category=category,
            expectation=expectation,
            passed=bool(final["is_passing"]),
            healing_attempts=int(final.get("retry_count", 0)),
            duration_s=time.perf_counter() - started,
            error_type=final.get("error_type"),
            input_tokens=int(final.get("input_tokens", 0)),
            output_tokens=int(final.get("output_tokens", 0)),
            cost_usd=float(final.get("cost_usd", 0.0)),
            llm_calls=int(final.get("llm_calls", 0)),
        )
        span.set_attribute("sdet.eval_as_expected", result.as_expected)
        span.set_attribute("sdet.cost_usd", round(result.cost_usd, 6))
        return result


def summarize(results: list[SpecResult]) -> EvalSummary:
    """Aggregate raw results. Pure function — this is what the unit tests exercise."""
    total = len(results)
    by_category: dict[str, dict[str, int]] = {}
    failure_modes: dict[str, int] = {}

    for r in results:
        bucket = by_category.setdefault(r.category, {"total": 0, "as_expected": 0})
        bucket["total"] += 1
        bucket["as_expected"] += int(r.as_expected)
        if not r.passed:
            key = r.crashed.split(":")[0] if r.crashed else (r.error_type or "Unknown")
            failure_modes[key] = failure_modes.get(key, 0) + 1

    healed = sum(1 for r in results if r.passed and r.healing_attempts > 0)
    gave_up = sum(1 for r in results if not r.passed and not r.crashed)
    latencies = [r.duration_s for r in results]

    return EvalSummary(
        total=total,
        passed=sum(1 for r in results if r.passed),
        first_pass=sum(1 for r in results if r.first_pass),
        healed=healed,
        gave_up=gave_up,
        crashed=sum(1 for r in results if r.crashed),
        as_expected=sum(1 for r in results if r.as_expected),
        avg_healing_attempts=(sum(r.healing_attempts for r in results) / total if total else 0.0),
        total_cost_usd=sum(r.cost_usd for r in results),
        total_tokens=sum(r.input_tokens + r.output_tokens for r in results),
        llm_calls=sum(r.llm_calls for r in results),
        p50_latency_s=percentile(latencies, 50),
        p95_latency_s=percentile(latencies, 95),
        failure_modes=dict(sorted(failure_modes.items(), key=lambda kv: -kv[1])),
        by_category=by_category,
    )


def run_eval(paths: list[Path], workers: int = 4, on_done=None) -> list[SpecResult]:
    """Run the corpus, optionally in parallel. Results come back in corpus order."""
    if workers <= 1:
        results = []
        for path in paths:
            result = run_spec(path)
            results.append(result)
            if on_done:
                on_done(result)
        return results

    collected: dict[int, SpecResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_spec, p): i for i, p in enumerate(paths)}
        for future in as_completed(futures):
            result = future.result()
            collected[futures[future]] = result
            if on_done:
                on_done(result)
    return [collected[i] for i in range(len(paths))]
