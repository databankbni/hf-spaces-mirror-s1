from typing import TypedDict, Optional, List, Annotated
from langgraph.graph.message import add_messages
from src.agent.schemas import TriageOutput

class TicketInput(TypedDict):
    ticket_id: str
    body: str
    customer_id: str
    tenant_id: str
    customer_tier: str

def merge_models(left: Optional[List[str]], right: Optional[List[str]]) -> List[str]:
    left_list = left or []
    right_list = right or []
    res = list(left_list)
    for x in right_list:
        if x not in res:
            res.append(x)
    return res

def merge_steps(left: Optional[str], right: Optional[str]) -> str:
    if not left:
        return right or ""
    if not right:
        return left
    if right in left:
        return left
    return f"{left},{right}"

class AgentState(TypedDict):
    # Input
    ticket: TicketInput

    # Populated by each sub-agent
    category: Optional[str]
    priority: Optional[str]
    routing_team: Optional[str]
    sla_breach_risk: Optional[float]
    churn_risk: Optional[float]
    confidence: Optional[float]
    summary: Optional[str]
    suggested_resolution: Optional[str]
    kb_citations: Optional[List[str]]
    recalled_memories: Optional[List[str]]
    incident_detected: Optional[bool]
    hitl_required: Optional[bool]
    hitl_reason: Optional[str]
    models_used: Annotated[Optional[List[str]], merge_models]

    # Workflow metadata
    current_step: Annotated[Optional[str], merge_steps]
    error: Optional[str]
    final_output: Optional[TriageOutput]

    # Messages (for LangGraph message passing)
    messages: Annotated[list, add_messages]
