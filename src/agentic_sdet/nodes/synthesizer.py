import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agentic_sdet.models.schemas import AgentState, GeneratedTestSuite
from agentic_sdet.telemetry.cost import record_usage_on_span, usage_from_message
from agentic_sdet.telemetry.tracer import tracer

MODEL_NAME = os.getenv("SDET_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = (
    "You are a senior SDET. Write complete, runnable Pytest suites with explicit, "
    "meaningful assertions. Avoid over-mocking: prefer exercising real behaviour. "
    "The file must be self-contained and runnable with `pytest <file>`."
)


def synthesizer_node(state: AgentState) -> dict:
    """Turn a natural-language specification into an executable Pytest suite."""
    with tracer.start_as_current_span("agent.synthesize_test") as span:
        span.set_attribute("sdet.spec_length", len(state["spec_content"]))
        span.set_attribute("gen_ai.request.model", MODEL_NAME)

        llm = ChatOpenAI(model=MODEL_NAME, temperature=0.0)
        # include_raw keeps the underlying AIMessage reachable, which is where the
        # token counts live; the parsed object alone would discard them.
        structured_llm = llm.with_structured_output(GeneratedTestSuite, include_raw=True)

        prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", "Requirement / specification:\n{spec}")]
        )

        response = (prompt | structured_llm).invoke({"spec": state["spec_content"]})
        result: GeneratedTestSuite = response["parsed"]
        usage = usage_from_message(response.get("raw"), MODEL_NAME)
        record_usage_on_span(span, usage)

        span.set_attribute("sdet.generated_lines", len(result.test_code.splitlines()))
        return {
            "generated_code": result.test_code,
            "retry_count": state.get("retry_count", 0),
            "is_passing": False,
            "input_tokens": state.get("input_tokens", 0) + usage.input_tokens,
            "output_tokens": state.get("output_tokens", 0) + usage.output_tokens,
            "cost_usd": state.get("cost_usd", 0.0) + usage.cost_usd,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }
