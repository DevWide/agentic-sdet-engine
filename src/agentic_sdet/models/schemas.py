from typing import Optional, TypedDict

from pydantic import BaseModel, Field


class GeneratedTestSuite(BaseModel):
    """Structured contract the LLM must fill in — no free-form parsing."""

    test_code: str = Field(description="Runnable Python file containing the Pytest suite")
    description: str = Field(description="Short explanation of the testing strategy")


class AgentState(TypedDict, total=False):
    """Shared state passed between every node of the graph.

    Token and cost fields accumulate across nodes: each LLM node adds its own usage to
    the running totals, so the final state carries the whole run's economics.
    """

    spec_content: str
    generated_code: Optional[str]
    execution_output: Optional[str]
    is_passing: bool
    retry_count: int
    error_type: Optional[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    llm_calls: int
