import tempfile
import subprocess
from pathlib import Path
from agentic_sdet.models.schemas import AgentState
from agentic_sdet.telemetry.tracer import tracer

def executor_node(state: AgentState) -> dict:
    with tracer.start_as_current_span("sdet.execute_sandbox_test") as span:
        code = state["generated_code"]
        
        # Salva o script gerado em um arquivo temporário para rodar com o Pytest local
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_sandbox.py"
            test_file.write_text(code, encoding="utf-8")
            
            span.set_attribute("sdet.sandbox_path", str(test_file))
            
            result = subprocess.run(
                ["pytest", str(test_file), "-v"],
                capture_output=True,
                text=True
            )
            
            is_success = (result.returncode == 0)
            output = result.stdout if is_success else f"{result.stdout}\n{result.stderr}"
            
            span.set_attribute("sdet.test_passed", is_success)
            span.set_attribute("sdet.pytest_exit_code", result.returncode)
            
            return {
                "execution_output": output,
                "is_passing": is_success,
                "error_type": "AssertionError" if not is_success else None
            }