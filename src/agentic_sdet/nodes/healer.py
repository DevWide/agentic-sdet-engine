import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agentic_sdet.models.schemas import AgentState, GeneratedTestSuite
from agentic_sdet.telemetry.cost import record_usage_on_span, usage_from_message
from agentic_sdet.telemetry.tracer import tracer

MODEL_NAME = os.getenv("SDET_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = (
    "You are a test self-healing specialist. The Pytest run failed. Read the traceback, "
    "find the root cause, and repair the suite while preserving what the original "
    "requirement is meant to validate. Never weaken an assertion just to make it pass."
)


def healer_node(state: AgentState) -> dict:
    """Repair a failing suite using the Pytest traceback as feedback."""
    with tracer.start_as_current_span("agent.self_healing_repair") as span:
        current_retry = state.get("retry_count", 0) + 1
        span.set_attribute("sdet.retry_attempt", current_retry)
        span.set_attribute("gen_ai.request.model", MODEL_NAME)
        if state.get("error_type"):
            span.set_attribute("sdet.error_type", state["error_type"])

        llm = ChatOpenAI(model=MODEL_NAME, temperature=0.0)
        structured_llm = llm.with_structured_output(GeneratedTestSuite, include_raw=True)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                (
                    "human",
                    "Original requirement:\n{spec}\n\n"
                    "Current code:\n{code}\n\n"
                    "Pytest output ({error_type}):\n{error}",
                ),
            ]
        )

        response = (prompt | structured_llm).invoke(
            {
                "code": state["generated_code"],
                "error": state["execution_output"],
                "error_type": state.get("error_type") or "UnknownError",
                "spec": state["spec_content"],
            }
        )
        result: GeneratedTestSuite = response["parsed"]
        usage = usage_from_message(response.get("raw"), MODEL_NAME)
        record_usage_on_span(span, usage)

        return {
            "generated_code": result.test_code,
            "retry_count": current_retry,
            "input_tokens": state.get("input_tokens", 0) + usage.input_tokens,
            "output_tokens": state.get("output_tokens", 0) + usage.output_tokens,
            "cost_usd": state.get("cost_usd", 0.0) + usage.cost_usd,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }
