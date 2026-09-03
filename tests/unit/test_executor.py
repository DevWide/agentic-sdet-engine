"""Sandbox tests: the executor really shells out to Pytest, so no LLM is involved."""

import pytest

from agentic_sdet.nodes import executor as executor_module
from agentic_sdet.nodes.executor import SuiteReport, _classify_failure, executor_node

PASSING_SUITE = """
def add(a, b):
    return a + b

def test_add():
    assert add(2, 3) == 5
"""

FAILING_SUITE = """
def test_wrong():
    assert 1 + 1 == 3
"""

BROKEN_SUITE = """
def test_missing_colon()
    assert True
"""

HANGING_SUITE = """
def test_forever():
    while True:
        pass
"""


def _run(code):
    return executor_node({"generated_code": code})


def test_passing_suite_is_reported_as_green():
    result = _run(PASSING_SUITE)

    assert result["is_passing"] is True
    assert result["error_type"] is None
    assert "1 passed" in result["execution_output"]


def test_failing_assertion_is_classified():
    result = _run(FAILING_SUITE)

    assert result["is_passing"] is False
    assert result["error_type"] == "AssertionError"
    assert "test_wrong" in result["execution_output"]


def test_syntax_error_is_classified_not_swallowed():
    result = _run(BROKEN_SUITE)

    assert result["is_passing"] is False
    # A file that cannot even be imported must not be labelled an assertion failure.
    assert result["error_type"] in {"SyntaxError", "CollectionError"}


def test_infinite_loop_is_cut_off_by_the_timeout(monkeypatch):
    monkeypatch.setattr(executor_module, "SANDBOX_TIMEOUT_SECONDS", 3)

    result = _run(HANGING_SUITE)

    assert result["is_passing"] is False
    assert result["error_type"] == "TimeoutError"
    assert "timeout" in result["execution_output"].lower()


def test_sandbox_directory_is_removed_after_the_run():
    # The generated file lives in a TemporaryDirectory; nothing may survive the call.
    import pathlib

    result = _run(PASSING_SUITE)
    assert result["is_passing"] is True
    assert not pathlib.Path("test_sandbox.py").exists()


@pytest.mark.parametrize(
    ("exit_code", "output", "expected"),
    [
        (2, "INTERNALERROR", "CollectionError"),
        (1, "E   SyntaxError: invalid syntax", "SyntaxError"),
        (5, "no tests ran", "NoTestsCollected"),
        (1, "E   AssertionError: nope", "AssertionError"),
        (1, "E   ZeroDivisionError: division by zero", "RuntimeError"),
    ],
)
def test_classify_failure_mapping(exit_code, output, expected):
    assert _classify_failure(exit_code, output, SuiteReport()) == expected


SKIPPED_SUITE = """
import pytest

try:
    from nonexistent_pkg_xyz import thing
except ImportError:
    thing = None

def test_thing():
    if thing is None:
        pytest.skip("dependency missing")
    assert thing() == 1
"""

PARTIALLY_SKIPPED_SUITE = """
import pytest

def test_real():
    assert 1 + 1 == 2

@pytest.mark.skip(reason="not ready")
def test_skipped():
    assert False
"""


def test_all_skipped_suite_is_not_a_pass():
    # Regression: pytest exits 0 on an all-skipped suite. Verifying nothing is not passing.
    result = _run(SKIPPED_SUITE)

    assert result["is_passing"] is False
    assert result["error_type"] == "AllTestsSkipped"
    assert "nothing was actually verified" in result["execution_output"]


def test_suite_with_one_real_test_still_passes_despite_a_skip():
    result = _run(PARTIALLY_SKIPPED_SUITE)

    assert result["is_passing"] is True
    assert result["error_type"] is None


def test_suite_report_counts_only_executed_tests():
    assert SuiteReport(tests=5, skipped=2).executed == 3
    assert SuiteReport(tests=3, skipped=3).executed == 0


def test_classify_prefers_all_skipped_over_exit_code():
    report = SuiteReport(tests=2, skipped=2, parsed=True)
    assert _classify_failure(0, "2 skipped", report) == "AllTestsSkipped"
