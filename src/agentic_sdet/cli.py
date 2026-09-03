from dotenv import load_dotenv
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from agentic_sdet.telemetry.tracer import tracer, flush_telemetry

load_dotenv()
from agentic_sdet.graph import build_sdet_graph

app = typer.Typer(help="Autonomous SDET & Self-Healing Testing Engine")
console = Console()

@app.command()
def run(spec_path: Path = typer.Argument(..., exists=True, help="Arquivo com requisito/user story")):
    """Executa a síntese, execução e autocura do teste."""
    spec_text = spec_path.read_text(encoding="utf-8")
    console.print(Panel(spec_text, title="[bold cyan]Especificação de Entrada[/bold cyan]"))
    
    graph = build_sdet_graph()
    
    with console.status("[bold green]Executando Grafo de Agentes com Telemetria OTel..."):
        final_state = graph.invoke({
            "spec_content": spec_text,
            "retry_count": 0,
            "is_passing": False
        })
        
    status_color = "green" if final_state["is_passing"] else "red"
    console.print(Panel(
        f"[bold]Status:[/bold] [{'green' if final_state['is_passing'] else 'red'}]{'Aprovado (Passou nos Testes)' if final_state['is_passing'] else 'Falhou após limite de tentativas'}[/]\n"
        f"[bold]Tentativas de Self-Healing:[/bold] {final_state['retry_count']}",
        title="Resultado da Execução",
        border_style=status_color
    ))
    
    console.print("\n[bold]Código Final Gerado:[/bold]")
    console.print(Syntax(final_state["generated_code"], "python", theme="monokai", line_numbers=True))

    flush_telemetry()  # Força o envio de todos os traces antes de encerrar o CLI

if __name__ == "__main__":
    app()