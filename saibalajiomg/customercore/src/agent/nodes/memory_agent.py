from src.agent.state import AgentState
from src.agent.memory import recall_memories
import structlog

log = structlog.get_logger()

def memory_agent_node(state: AgentState) -> AgentState:
    ticket = state["ticket"]
    customer_id = ticket["customer_id"]
    tenant_id = ticket["tenant_id"]
    body = ticket["body"]

    # Recall up to 3 relevant long-term memories
    memories = recall_memories(customer_id, tenant_id, query=body, limit=3)

    log.info("memory_agent_done", customer_id=customer_id, memories_recalled=len(memories))
    return {
        "recalled_memories": memories,
        "current_step": "memory_agent",
    }
