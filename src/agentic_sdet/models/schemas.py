from typing import TypedDict, Optional, List
from pydantic import BaseModel, Field

class GeneratedTestSuite(BaseModel):
    test_code: str = Field(description="Código Python executável contendo os testes com Pytest")
    description: str = Field(description="Explicação breve da estratégia de teste")

class AgentState(TypedDict):
    spec_content: str
    generated_code: Optional[str]
    execution_output: Optional[str]
    is_passing: bool
    retry_count: int
    error_type: Optional[str]