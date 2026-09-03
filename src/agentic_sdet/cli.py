import json
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Optional

# Runtime noise from transitive deps during the LLM calls. The LangGraph
# PendingDeprecationWarning is not filterable here: langchain_core installs an
# "always" filter of its own while importing, which overrides anything set first.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*Pydantic serializer warnings.*")

import typer  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.syntax import Syntax  # noqa: E402
from rich.table import Table  # noqa: E402

load_dotenv()

from agentic_sdet.evaluation.runner import (  # noqa: E402
    EXPECTATIONS,
    EvalSummary,
    SpecResult,
    run_eval,
    summarize,
)
from agentic_sdet.graph import MAX_HEALING_RETRIES, build_sdet_graph  # noqa: E402
from agentic_sdet.nodes.synthesizer import MODEL_NAME  # noqa: E402
from agentic_sdet.telemetry.tracer import flush_telemetry, tracer  # noqa: E402

app = typer.Typer(help="Autonomous SDET & self-healing testing engine")
# record=True keeps the rendered output in memory so --save-svg can export it.
console = Console(record=True)


def _export_svg(path: Optional[Path], title: str) -> None:
    """Write the console session to a standalone SVG — no screenshot tooling needed."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(path), title=title)
    console.print(f"\n[dim]Session exported to {path}[/]")


OUTCOME_STYLE = {
    "pass_first_try": ("green", "pass"),
    "pass_after_healing": ("yellow", "healed"),
    "give_up": ("red", "gave up"),
    "crashed": ("magenta", "crashed"),
}


@app.command()
def run(
    spec_path: Path = typer.Argument(
        ..., exists=True, help="File holding the requirement / user story"
    ),
    save_svg: Optional[Path] = typer.Option(
        None, "--save-svg", help="Export the terminal session to an SVG file"
    ),
) -> None:
    """Synthesize a Pytest suite from a spec, run it, and self-heal it until it passes."""
    spec_text = spec_path.read_text(encoding="utf-8")
    console.print(Panel(spec_text, title="[bold cyan]Input specification[/bold cyan]"))

    graph = build_sdet_graph()

    # Root span: without it every node would emit its own orphan trace.
    with tracer.start_as_current_span("sdet.run") as root_span:
        root_span.set_attribute("sdet.spec_file", spec_path.name)
        root_span.set_attribute("sdet.max_retries", MAX_HEALING_RETRIES)

        with console.status("[bold green]Running the agent graph with OTel tracing..."):
            final_state = graph.invoke(
                {"spec_content": spec_text, "retry_count": 0, "is_passing": False}
            )

        passed = final_state["is_passing"]
        root_span.set_attribute("sdet.run_passed", passed)
        root_span.set_attribute("sdet.healing_attempts", final_state["retry_count"])
        root_span.set_attribute("sdet.cost_usd", round(final_state.get("cost_usd", 0.0), 6))

    status_color = "green" if passed else "red"
    status_label = "Passed" if passed else f"Failed after {MAX_HEALING_RETRIES} healing attempts"

    console.print(
        Panel(
            f"[bold]Status:[/bold] [{status_color}]{status_label}[/]\n"
            f"[bold]Self-healing attempts:[/bold] {final_state['retry_count']}\n"
            f"[bold]LLM calls:[/bold] {final_state.get('llm_calls', 0)}  "
            f"[bold]Tokens:[/bold] {final_state.get('input_tokens', 0)} in / "
            f"{final_state.get('output_tokens', 0)} out  "
            f"[bold]Cost:[/bold] ${final_state.get('cost_usd', 0.0):.5f}",
            title="Run result",
            border_style=status_color,
        )
    )

    console.print("\n[bold]Final generated suite:[/bold]")
    console.print(
        Syntax(final_state["generated_code"], "python", theme="monokai", line_numbers=True)
    )

    _export_svg(save_svg, f"agentic-sdet run {spec_path.name}")

    flush_telemetry()
    raise typer.Exit(code=0 if passed else 1)


def _render_results(results: list) -> None:
    table = Table(title="Per-spec results", title_justify="left", header_style="bold")
    table.add_column("Spec")
    table.add_column("Category")
    table.add_column("Outcome")
    table.add_column("Heals", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("As expected", justify="center")

    for r in results:
        color, label = OUTCOME_STYLE[r.outcome]
        table.add_row(
            r.name,
            r.category,
            f"[{color}]{label}[/]",
            str(r.healing_attempts),
            f"{r.duration_s:.1f}s",
            f"${r.cost_usd:.5f}",
            "[green]yes[/]" if r.as_expected else "[red]NO[/]",
        )
    console.print(table)


def _render_summary(s: EvalSummary) -> None:
    body = (
        f"[bold]Behaved as designed:[/bold] {s.as_expected}/{s.total} "
        f"({s.expectation_rate:.0%})\n"
        f"[bold]Suite passed:[/bold]        {s.passed}/{s.total} ({s.pass_rate:.0%})\n"
        f"[bold]Passed first try:[/bold]    {s.first_pass}/{s.total} ({s.first_pass_rate:.0%})\n"
        f"[bold]Rescued by healer:[/bold]   {s.healed}/{s.healed + s.gave_up} "
        f"({s.healing_recovery_rate:.0%})\n"
        f"[bold]Avg healing attempts:[/bold] {s.avg_healing_attempts:.1f}\n"
        f"[bold]Cost:[/bold] ${s.total_cost_usd:.4f} total, "
        f"${s.avg_cost_usd:.5f}/spec  ({s.total_tokens:,} tokens, {s.llm_calls} LLM calls)\n"
        f"[bold]Latency:[/bold] p50 {s.p50_latency_s:.1f}s, p95 {s.p95_latency_s:.1f}s"
    )
    console.print(Panel(body, title="Evaluation summary", border_style="cyan"))

    if s.failure_modes:
        modes = "  ".join(f"{k}={v}" for k, v in s.failure_modes.items())
        console.print(f"[bold]Failure modes:[/bold] {modes}")

    cat_table = Table(header_style="bold")
    cat_table.add_column("Category")
    cat_table.add_column("Expected behaviour")
    cat_table.add_column("Matched", justify="right")
    for category, stats in sorted(s.by_category.items()):
        cat_table.add_row(
            category,
            EXPECTATIONS.get(category, "?"),
            f"{stats['as_expected']}/{stats['total']}",
        )
    console.print(cat_table)


@app.command(name="eval")
def evaluate(
    corpus: Path = typer.Option(
        Path("tests/fixtures/eval"), "--corpus", exists=True, help="Directory of spec files"
    ),
    only: Optional[str] = typer.Option(
        None, "--only", help="Run a single category, e.g. easy / heal / impossible"
    ),
    workers: int = typer.Option(4, "--workers", min=1, help="Specs to run concurrently"),
    json_out: Optional[Path] = typer.Option(
        None, "--json-out", help="Write the raw results as JSON (for CI trend tracking)"
    ),
    fail_under: Optional[float] = typer.Option(
        None,
        "--fail-under",
        help="Exit non-zero if the as-expected rate falls below this percentage",
    ),
    save_svg: Optional[Path] = typer.Option(
        None, "--save-svg", help="Export the terminal session to an SVG file"
    ),
) -> None:
    """Run the whole spec corpus and report success rate, healing recovery, cost and latency."""
    paths = sorted(p for p in corpus.glob("*.txt") if not only or p.stem.startswith(only))
    if not paths:
        console.print(f"[red]No specs matched in {corpus}[/]")
        raise typer.Exit(code=2)

    console.print(
        f"[bold cyan]Evaluating {len(paths)} specs[/] · model [bold]{MODEL_NAME}[/] · "
        f"max retries [bold]{MAX_HEALING_RETRIES}[/] · {workers} worker(s)\n"
    )

    done = 0

    def progress(result: SpecResult) -> None:
        nonlocal done
        done += 1
        color, label = OUTCOME_STYLE[result.outcome]
        console.print(f"  [{done:>2}/{len(paths)}] {result.name:<28} [{color}]{label}[/]")

    results = run_eval(paths, workers=workers, on_done=progress)
    console.print()

    _render_results(results)
    summary = summarize(results)
    _render_summary(summary)

    if json_out:
        payload = {
            "model": MODEL_NAME,
            "max_retries": MAX_HEALING_RETRIES,
            "summary": {
                "total": summary.total,
                "as_expected": summary.as_expected,
                "expectation_rate": round(summary.expectation_rate, 4),
                "pass_rate": round(summary.pass_rate, 4),
                "first_pass_rate": round(summary.first_pass_rate, 4),
                "healing_recovery_rate": round(summary.healing_recovery_rate, 4),
                "avg_healing_attempts": round(summary.avg_healing_attempts, 3),
                "total_cost_usd": round(summary.total_cost_usd, 6),
                "total_tokens": summary.total_tokens,
                "p50_latency_s": round(summary.p50_latency_s, 3),
                "p95_latency_s": round(summary.p95_latency_s, 3),
                "failure_modes": summary.failure_modes,
            },
            "results": [
                {**asdict(r), "outcome": r.outcome, "as_expected": r.as_expected} for r in results
            ],
        }
        json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"\n[dim]Raw results written to {json_out}[/]")

    _export_svg(save_svg, f"agentic-sdet eval ({len(paths)} specs)")

    flush_telemetry()

    if fail_under is not None and summary.expectation_rate * 100 < fail_under:
        console.print(
            f"\n[red]As-expected rate {summary.expectation_rate:.0%} is below "
            f"the {fail_under:.0f}% threshold[/]"
        )
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
