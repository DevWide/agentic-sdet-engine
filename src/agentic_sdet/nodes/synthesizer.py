from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from agentic_sdet.models.schemas import AgentState, GeneratedTestSuite
from agentic_sdet.telemetry.tracer import tracer

load_dotenv()

def synthesizer_node(state: AgentState) -> dict:
    with tracer.start_as_current_span("agent.synthesize_test") as span:
        span.set_attribute("sdet.spec_length", len(state["spec_content"]))
        
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        structured_llm = llm.with_structured_output(GeneratedTestSuite)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Você é um SDET Sênior. Escreva testes automatizados em Pytest completos, sem mocks excessivos, com asserts claros."),
            ("human", "Requisito / Especificação:\n{spec}")
        ])
        
        chain = prompt | structured_llm
        result: GeneratedTestSuite = chain.invoke({"spec": state["spec_content"]})
        
        span.set_attribute("sdet.generated_lines", len(result.test_code.splitlines()))
        return {
            "generated_code": result.test_code,
            "retry_count": state.get("retry_count", 0),
            "is_passing": False
        }