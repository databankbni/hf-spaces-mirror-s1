import structlog
from typing import List
from src.agent.state import AgentState

log = structlog.get_logger()

def compute_confidence(state: AgentState) -> float:
    """
    Evaluate triage confidence based on category ambiguity, input lengths,
    and models used during processing.
    """
    confidence = 0.90  # Default high-fidelity baseline
    
    ticket = state["ticket"]
    body = ticket["body"]
    category = state.get("category", "other")
    models_used = state.get("models_used") or []
    
    # 1. Ticket length penalty (extremely short or long tickets add ambiguity)
    body_len = len(body.strip())
    if body_len < 10:
        confidence -= 0.35  # extremely short, practically zero context
    elif body_len < 30:
        confidence -= 0.15
    elif body_len > 2500:
        confidence -= 0.05
        
    # 2. Category ambiguity penalty
    if category == "other":
        confidence -= 0.10
        
    # 3. Model pedigree penalty: using fallback heuristics rather than ML/LLM models
    if "heuristic-classifier-v1.0" in models_used:
        confidence -= 0.05
    if "heuristic-rag-fallback-v1.0" in models_used:
        confidence -= 0.10
        
    # 4. Risk premium check: elevated churn/SLA risks make the triage decision more sensitive
    churn_risk = state.get("churn_risk") or 0.0
    sla_risk = state.get("sla_breach_risk") or 0.0
    if churn_risk > 0.70 or sla_risk > 0.75:
        confidence -= 0.05
        
    return max(0.1, min(1.0, round(confidence, 2)))

def hitl_agent_node(state: AgentState) -> AgentState:
    priority = state.get("priority", "medium")
    category = state.get("category", "other")
    sla_breach_risk = state.get("sla_breach_risk") or 0.0
    churn_risk = state.get("churn_risk") or 0.0
    
    models_used: List[str] = state.get("models_used") or []
    models_used.append("hitl-threshold-evaluator-v1.0")
    
    # Calculate confidence score
    confidence = compute_confidence(state)
    
    # Evaluate HITL (Human-in-the-loop) criteria
    hitl_required = False
    reasons = []
    
    if confidence < 0.65:
        hitl_required = True
        reasons.append(f"Low confidence ({confidence:.2f} < 0.65)")
        
    if sla_breach_risk > 0.80:
        hitl_required = True
        reasons.append(f"Critical SLA breach risk ({sla_breach_risk:.2f} > 0.80)")
        
    if churn_risk > 0.75 and priority in ["high", "critical"]:
        hitl_required = True
        reasons.append(f"High churn risk ({churn_risk:.2f} > 0.75) on high/critical priority ticket")
        
    if category == "security":
        # Enterprise policy: ALWAYS review security incidents to ensure data privacy and legal compliance
        hitl_required = True
        reasons.append("Security compliance policy review required")
        
    hitl_reason = "; ".join(reasons) if hitl_required else None
    
    log.info(
        "hitl_agent_done",
        confidence=confidence,
        hitl_required=hitl_required,
        hitl_reason=hitl_reason
    )
    
    return {
        **state,
        "confidence": confidence,
        "hitl_required": hitl_required,
        "hitl_reason": hitl_reason,
        "current_step": "hitl_agent",
        "models_used": models_used,
    }
