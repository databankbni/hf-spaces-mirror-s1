import structlog
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.agent.state import AgentState
from src.agent.schemas import TriageOutput
from src.agent.nodes.classify_agent import classify_agent_node
from src.agent.nodes.memory_agent import memory_agent_node
from src.agent.nodes.rag_agent import rag_agent_node
from src.agent.nodes.churn_agent import churn_agent_node
from src.agent.nodes.incident_agent import incident_agent_node
from src.agent.nodes.hitl_agent import hitl_agent_node

log = structlog.get_logger()

def hitl_interrupt_node(state: AgentState) -> AgentState:
    """Break point identity node. Execution halts immediately before this node is run."""
    log.info("hitl_interrupt_node_reached_pausing")
    return state

def finalize_node(state: AgentState) -> AgentState:
    """Assembles all calculated parameters into a strict, validated TriageOutput."""
    log.info("finalizing_agent_state_compiling_schema")
    
    # Default fallbacks to ensure compliance with field validators/minimum lengths
    summary = state.get("summary") or "Ticket requiring triage."
    if len(summary) < 10:
        summary = (summary + " " * 10)[:15]
        
    suggested_resolution = state.get("suggested_resolution") or "Resolution pending."
    if len(suggested_resolution) < 10:
        suggested_resolution = (suggested_resolution + " " * 10)[:15]
        
    final_output = TriageOutput(
        category=state.get("category") or "other",
        priority=state.get("priority") or "medium",
        routing_team=state.get("routing_team") or "support",
        sla_breach_risk=state.get("sla_breach_risk") or 0.0,
        churn_risk=state.get("churn_risk") or 0.0,
        confidence=state.get("confidence") or 0.5,
        summary=summary,
        suggested_resolution=suggested_resolution,
        kb_citations=state.get("kb_citations") or [],
        recalled_memories=state.get("recalled_memories") or [],
        incident_detected=state.get("incident_detected") or False,
        hitl_required=state.get("hitl_required") or False,
        hitl_reason=state.get("hitl_reason"),
        models_used=state.get("models_used") or []
    )
    
    return {
        **state,
        "final_output": final_output,
        "current_step": "finalize"
    }

# ── Define the Agentic State Workflow ──────────────────────────────────────────
workflow = StateGraph(AgentState)

# 1. Register specialized sub-agent nodes
workflow.add_node("classify", classify_agent_node)
workflow.add_node("memory", memory_agent_node)
workflow.add_node("rag", rag_agent_node)
workflow.add_node("churn", churn_agent_node)
workflow.add_node("incident", incident_agent_node)
workflow.add_node("hitl", hitl_agent_node)
workflow.add_node("hitl_interrupt", hitl_interrupt_node)
workflow.add_node("finalize", finalize_node)

# 2. Add structural parallel concurrency (Phase 15 - Latency Optimization)
# Step 1: Run 'classify' and 'memory' concurrently
workflow.add_edge(START, "classify")
workflow.add_edge(START, "memory")

# Step 2: Once 'classify' and 'memory' are both complete, run 'rag', 'churn', and 'incident' concurrently
workflow.add_edge("classify", "rag")
workflow.add_edge("memory", "rag")

workflow.add_edge("classify", "churn")
workflow.add_edge("memory", "churn")

workflow.add_edge("classify", "incident")
workflow.add_edge("memory", "incident")

# Step 3: Join the concurrent branches from 'rag', 'churn', and 'incident' at 'hitl'
workflow.add_edge("rag", "hitl")
workflow.add_edge("churn", "hitl")
workflow.add_edge("incident", "hitl")

# 3. Add conditional Human-in-the-loop gating
def hitl_check_router(state: AgentState) -> str:
    """Enforce human intercept routing if flagged by the HITL agent."""
    if state.get("hitl_required"):
        log.info("routing_to_human_interrupt")
        return "hitl_interrupt"
    log.info("routing_directly_to_finalize")
    return "finalize"

workflow.add_conditional_edges(
    "hitl",
    hitl_check_router,
    {
        "hitl_interrupt": "hitl_interrupt",
        "finalize": "finalize"
    }
)

# 4. Final transitions
workflow.add_edge("hitl_interrupt", "finalize")
workflow.add_edge("finalize", END)

# ── Compile the Graph with Durable Memory Checkpointer ─────────────────────────
memory_checkpointer = MemorySaver()
app = workflow.compile(
    checkpointer=memory_checkpointer,
    interrupt_before=["hitl_interrupt"]
)

# ── Public Entry Points for the Triage Pipeline ────────────────────────────────

def run_triage(ticket: dict, thread_id: str = "default-thread") -> TriageOutput:
    """
    Run the multi-agent triage pipeline.
    
    If the graph hits a Human-in-the-loop interruption, the state is paused,
    and a preliminary TriageOutput is returned with hitl_required=True.
    Use resume_triage() to proceed.
    """
    initial_state = {
        "ticket": ticket,
        "category": None,
        "priority": None,
        "routing_team": None,
        "sla_breach_risk": None,
        "churn_risk": None,
        "confidence": None,
        "summary": None,
        "suggested_resolution": None,
        "kb_citations": None,
        "recalled_memories": None,
        "incident_detected": None,
        "hitl_required": None,
        "hitl_reason": None,
        "models_used": [],
        "current_step": "start",
        "error": None,
        "final_output": None,
        "messages": []
    }
    
    config = {"configurable": {"thread_id": thread_id}}
    
    # Execute the graph
    for event in app.stream(initial_state, config):
        pass
        
    state_snapshot = app.get_state(config)
    if state_snapshot.next:
        # Paused before hitl_interrupt. Assemble from current intermediate parameters.
        current_values = state_snapshot.values
        
        summary = current_values.get("summary") or "Ticket awaiting triage review."
        if len(summary) < 10:
            summary = (summary + " " * 10)[:15]
            
        suggested_resolution = current_values.get("suggested_resolution") or "Pending human triage approval."
        if len(suggested_resolution) < 10:
            suggested_resolution = (suggested_resolution + " " * 10)[:15]
            
        return TriageOutput(
            category=current_values.get("category") or "other",
            priority=current_values.get("priority") or "medium",
            routing_team=current_values.get("routing_team") or "support",
            sla_breach_risk=current_values.get("sla_breach_risk") or 0.0,
            churn_risk=current_values.get("churn_risk") or 0.0,
            confidence=current_values.get("confidence") or 0.5,
            summary=summary,
            suggested_resolution=suggested_resolution,
            kb_citations=current_values.get("kb_citations") or [],
            recalled_memories=current_values.get("recalled_memories") or [],
            incident_detected=current_values.get("incident_detected") or False,
            hitl_required=True,
            hitl_reason=current_values.get("hitl_reason") or "Manual review required.",
            models_used=current_values.get("models_used") or []
        )
        
    return state_snapshot.values.get("final_output")

def resume_triage(thread_id: str, overrides: Optional[Dict[str, Any]] = None) -> TriageOutput:
    """
    Resume an interrupted triage pipeline, optionally applying human corrections.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    if overrides:
        # Human agent overrides the AI decisions
        app.update_state(config, overrides)
        
    # Resume graph execution
    for event in app.stream(None, config):
        pass
        
    state_snapshot = app.get_state(config)
    return state_snapshot.values.get("final_output")
