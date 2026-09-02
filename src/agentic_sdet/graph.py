from langgraph.graph import StateGraph, END
from agentic_sdet.models.schemas import AgentState
from agentic_sdet.nodes.synthesizer import synthesizer_node
from agentic_sdet.nodes.executor import executor_node
from agentic_sdet.nodes.healer import healer_node

def should_continue(state: AgentState):
    if state["is_passing"]:
        return "approved"
    if state.get("retry_count", 0) >= 3:
        return "max_retries_reached"
    return "heal"

def build_sdet_graph():
    workflow = StateGraph(AgentState)
    
    # Adiciona os nós
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("healer", healer_node)
    
    # Define o fluxo
    workflow.set_entry_point("synthesizer")
    workflow.add_edge("synthesizer", "executor")
    
    # Transições condicionais (Ciclo de Feedback)
    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "approved": END,
            "max_retries_reached": END,
            "heal": "healer"
        }
    )
    workflow.add_edge("healer", "executor")
    
    return workflow.compile()