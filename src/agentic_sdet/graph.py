import os

from langgraph.graph import END, StateGraph

from agentic_sdet.models.schemas import AgentState
from agentic_sdet.nodes.executor import executor_node
from agentic_sdet.nodes.healer import healer_node
from agentic_sdet.nodes.synthesizer import synthesizer_node

MAX_HEALING_RETRIES = int(os.getenv("SDET_MAX_RETRIES", "3"))


def should_continue(state: AgentState) -> str:
    """Decide whether the graph is done, exhausted, or should attempt another repair."""
    if state["is_passing"]:
        return "approved"
    if state.get("retry_count", 0) >= MAX_HEALING_RETRIES:
        return "max_retries_reached"
    return "heal"


def build_sdet_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("healer", healer_node)

    workflow.set_entry_point("synthesizer")
    workflow.add_edge("synthesizer", "executor")

    # Feedback cycle: a failing run routes back through the healer.
    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "approved": END,
            "max_retries_reached": END,
            "heal": "healer",
        },
    )
    workflow.add_edge("healer", "executor")

    return workflow.compile()
