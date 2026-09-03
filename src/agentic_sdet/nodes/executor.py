import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from agentic_sdet.models.schemas import AgentState
from agentic_sdet.telemetry.tracer import tracer

# A generated suite that loops forever must not hang the whole graph.
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("SDET_SANDBOX_TIMEOUT", "60"))


class SuiteReport:
    """What the JUnit XML says actually happened, as opposed to the exit code."""

    __slots__ = ("tests", "failures", "errors", "skipped", "parsed")

    def __init__(self, tests=0, failures=0, errors=0, skipped=0, parsed=False):
        self.tests = tests
        self.failures = failures
        self.errors = errors
        self.skipped = skipped
        self.parsed = parsed

    @property
    def executed(self) -> int:
        """Tests that actually ran an assertion — skips verify nothing."""
        return self.tests - self.skipped


def parse_junit_report(report_path: Path) -> SuiteReport:
    """Read pytest's JUnit XML. Returns an unparsed report if the file is absent/corrupt."""
    if not report_path.exists():
        return SuiteReport()
    try:
        root = ET.parse(report_path).getroot()
    except ET.ParseError:
        return SuiteReport()

    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    report = SuiteReport(parsed=True)
    for suite in suites:
        report.tests += int(suite.get("tests", 0))
        report.failures += int(suite.get("failures", 0))
        report.errors += int(suite.get("errors", 0))
        report.skipped += int(suite.get("skipped", 0))
    return report


def _classify_failure(exit_code: int, output: str, report: SuiteReport) -> str:
    """Map a Pytest run onto the error category the healing agent reasons about."""
    if report.parsed and report.tests > 0 and report.executed == 0:
        return "AllTestsSkipped"
    if exit_code in (2, 3, 4):
        return "CollectionError"
    if "SyntaxError" in output or "IndentationError" in output:
        return "SyntaxError"
    if exit_code == 5 or (report.parsed and report.tests == 0):
        return "NoTestsCollected"
    if "AssertionError" in output or "assert" in output:
        return "AssertionError"
    return "RuntimeError"


def _verify(exit_code: int, report: SuiteReport) -> bool:
    """A green run requires assertions that actually executed, not just exit code 0.

    Found by the eval harness: an agent facing an impossible spec wrapped everything in
    `pytest.skip(...)`. Pytest exits 0 on an all-skipped suite, so the engine reported
    success for a suite that verified nothing.
    """
    if exit_code != 0:
        return False
    if not report.parsed:
        return True  # No XML to check; fall back to the exit code alone.
    return report.executed > 0 and report.failures == 0 and report.errors == 0


def _skip_feedback(report: SuiteReport) -> str:
    return (
        f"\n\nENGINE NOTE: pytest exited 0 but {report.skipped} of {report.tests} tests were "
        "skipped, so nothing was actually verified. Rewrite the suite so the assertions run. "
        "Skipping, xfail, or wrapping a failing assertion in pytest.raises(AssertionError) "
        "does not satisfy the requirement."
    )


def executor_node(state: AgentState) -> dict:
    """Run the generated suite in a throwaway directory and report back to the graph."""
    with tracer.start_as_current_span("sdet.execute_sandbox_test") as span:
        code = state["generated_code"]

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_sandbox.py"
            test_file.write_text(code, encoding="utf-8")
            report_file = Path(tmpdir) / "report.xml"

            span.set_attribute("sdet.sandbox_path", str(test_file))
            span.set_attribute("sdet.sandbox_timeout_seconds", SANDBOX_TIMEOUT_SECONDS)

            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        str(test_file),
                        "-v",
                        "-p",
                        "no:cacheprovider",
                        f"--junit-xml={report_file}",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                    timeout=SANDBOX_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                span.set_attribute("sdet.test_passed", False)
                span.set_attribute("sdet.error_type", "TimeoutError")
                return {
                    "execution_output": (
                        f"Execution exceeded the {SANDBOX_TIMEOUT_SECONDS}s sandbox timeout. "
                        "The generated suite most likely contains an infinite loop "
                        "or a blocking call."
                    ),
                    "is_passing": False,
                    "error_type": "TimeoutError",
                }

            report = parse_junit_report(report_file)
            is_success = _verify(result.returncode, report)
            output = (
                result.stdout if result.returncode == 0 else (f"{result.stdout}\n{result.stderr}")
            )

            error_type: Optional[str] = None
            if not is_success:
                error_type = _classify_failure(result.returncode, output, report)
                if error_type == "AllTestsSkipped":
                    output += _skip_feedback(report)

            span.set_attribute("sdet.test_passed", is_success)
            span.set_attribute("sdet.pytest_exit_code", result.returncode)
            span.set_attribute("sdet.tests_total", report.tests)
            span.set_attribute("sdet.tests_executed", report.executed)
            span.set_attribute("sdet.tests_skipped", report.skipped)
            if error_type:
                span.set_attribute("sdet.error_type", error_type)

            return {
                "execution_output": output,
                "is_passing": is_success,
                "error_type": error_type,
            }
