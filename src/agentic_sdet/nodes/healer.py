from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from agentic_sdet.models.schemas import AgentState, GeneratedTestSuite
from agentic_sdet.telemetry.tracer import tracer

def healer_node(state: AgentState) -> dict:
    with tracer.start_as_current_span("agent.self_healing_repair") as span:
        current_retry = state.get("retry_count", 0) + 1
        span.set_attribute("sdet.retry_attempt", current_retry)
        
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        structured_llm = llm.with_structured_output(GeneratedTestSuite)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Você é um especialista em Self-Healing de testes. O teste falhou na execução do Pytest. Analise o erro e corrija o código de teste mantendo o objetivo de validação do requisito."),
            ("human", "Código Original:\n{code}\n\nErro do Pytest:\n{error}\n\nRequisito Original:\n{spec}")
        ])
        
        chain = prompt | structured_llm
        result: GeneratedTestSuite = chain.invoke({
            "code": state["generated_code"],
            "error": state["execution_output"],
            "spec": state["spec_content"]
        })
        
        return {
            "generated_code": result.test_code,
            "retry_count": current_retry
        }