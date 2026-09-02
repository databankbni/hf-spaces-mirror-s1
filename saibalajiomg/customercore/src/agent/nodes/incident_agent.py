import structlog
from typing import List
from src.agent.state import AgentState

log = structlog.get_logger()

# Keywords indicating an operational infrastructure or software incident
INCIDENT_KEYWORDS = [
    "outage", "completely down", "service unavailable", "is down", "not accessible",
    "500 error", "internal server error", "database connection failed", "server crash",
    "network failure", "incident", "dns failure", "timeout error", "api failure"
]

def scan_incident(body: str) -> bool:
    """Scan ticket body for operational incident indicator keywords."""
    text = body.lower()
    return any(kw in text for kw in INCIDENT_KEYWORDS)

def incident_agent_node(state: AgentState) -> AgentState:
    ticket = state["ticket"]
    body = ticket["body"]
    category = state.get("category", "other")
    priority = state.get("priority", "medium")
    tier = ticket.get("customer_tier", "free").lower()
    
    models_used: List[str] = state.get("models_used") or []
    models_used.append("incident-routing-heuristics-v1.0")
    
    # 1. Detect if this is an active/severe incident
    incident_detected = scan_incident(body) or (category == "incident")
    
    # 2. Determine routing team based on category, priority, and customer tier
    routing_team = "support"  # default
    
    if tier == "enterprise" and priority == "critical":
        # Enterprise VIP tickets requiring critical escalation route to dedicated escalation team
        routing_team = "escalation"
    elif category == "security":
        routing_team = "security"
    elif category == "billing":
        routing_team = "billing"
    elif category == "incident":
        routing_team = "infra"
    elif category == "performance":
        routing_team = "infra"
    elif category == "auth":
        routing_team = "security"
    elif category in ["bug", "feature_request"]:
        routing_team = "engineering"
    elif category in ["docs", "question", "other"]:
        routing_team = "support"
        
    # If an incident was detected but the ticket is not already routed to escalation/security/billing,
    # route to infra or engineering to address immediately
    if incident_detected and routing_team not in ["escalation", "security", "billing"]:
        if category in ["bug", "performance"]:
            routing_team = "engineering"
        else:
            routing_team = "infra"
            
    log.info("incident_agent_done", incident_detected=incident_detected, routing_team=routing_team)
    
    return {
        "incident_detected": incident_detected,
        "routing_team": routing_team,
        "current_step": "incident_agent",
        "models_used": models_used,
    }
