"""Graph-level tests: routing decisions and the self-healing cycle, with the LLM stubbed out."""

import pytest

from agentic_sdet import graph as graph_module
from agentic_sdet.graph import build_sdet_graph, should_continue


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"is_passing": True, "retry_count": 0}, "approved"),
        ({"is_passing": True, "retry_count": 99}, "approved"),
        ({"is_passing": False, "retry_count": 0}, "heal"),
        ({"is_passing": False, "retry_count": 2}, "heal"),
        ({"is_passing": False, "retry_count": 3}, "max_retries_reached"),
        ({"is_passing": False, "retry_count": 10}, "max_retries_reached"),
    ],
)
def test_should_continue_routes_each_outcome(state, expected):
    assert should_continue(state) == expected


def test_should_continue_defaults_missing_retry_count():
    assert should_continue({"is_passing": False}) == "heal"


def _stub_nodes(monkeypatch, failures_before_pass: int):
    """Replace the three nodes with deterministic stubs and record the call order."""
    calls = []

    def fake_synthesizer(state):
        calls.append("synthesizer")
        return {
            "generated_code": "def test_x(): assert True",
            "retry_count": 0,
            "is_passing": False,
        }

    def fake_executor(state):
        calls.append("executor")
        passing = state.get("retry_count", 0) >= failures_before_pass
        return {
            "execution_output": "ok" if passing else "AssertionError: boom",
            "is_passing": passing,
            "error_type": None if passing else "AssertionError",
        }

    def fake_healer(state):
        calls.append("healer")
        return {
            "generated_code": "# healed\ndef test_x(): assert True",
            "retry_count": state.get("retry_count", 0) + 1,
        }

    monkeypatch.setattr(graph_module, "synthesizer_node", fake_synthesizer)
    monkeypatch.setattr(graph_module, "executor_node", fake_executor)
    monkeypatch.setattr(graph_module, "healer_node", fake_healer)
    return calls


def test_graph_finishes_immediately_when_first_run_passes(monkeypatch):
    calls = _stub_nodes(monkeypatch, failures_before_pass=0)

    state = build_sdet_graph().invoke(
        {"spec_content": "spec", "retry_count": 0, "is_passing": False}
    )

    assert state["is_passing"] is True
    assert state["retry_count"] == 0
    assert calls == ["synthesizer", "executor"]


def test_graph_heals_until_the_suite_passes(monkeypatch):
    calls = _stub_nodes(monkeypatch, failures_before_pass=2)

    state = build_sdet_graph().invoke(
        {"spec_content": "spec", "retry_count": 0, "is_passing": False}
    )

    assert state["is_passing"] is True
    assert state["retry_count"] == 2
    assert calls == ["synthesizer", "executor", "healer", "executor", "healer", "executor"]
    assert state["generated_code"].startswith("# healed")


def test_graph_stops_at_the_retry_ceiling(monkeypatch):
    calls = _stub_nodes(monkeypatch, failures_before_pass=99)

    state = build_sdet_graph().invoke(
        {"spec_content": "spec", "retry_count": 0, "is_passing": False}
    )

    assert state["is_passing"] is False
    assert state["retry_count"] == graph_module.MAX_HEALING_RETRIES
    assert calls.count("healer") == graph_module.MAX_HEALING_RETRIES
    assert calls.count("executor") == graph_module.MAX_HEALING_RETRIES + 1


def test_retry_ceiling_is_configurable(monkeypatch):
    monkeypatch.setattr(graph_module, "MAX_HEALING_RETRIES", 1)
    _stub_nodes(monkeypatch, failures_before_pass=99)

    state = build_sdet_graph().invoke(
        {"spec_content": "spec", "retry_count": 0, "is_passing": False}
    )

    assert state["retry_count"] == 1
    assert state["is_passing"] is False
