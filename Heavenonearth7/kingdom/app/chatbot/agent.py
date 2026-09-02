"""
Heaven on Earth CMS Backend — LangGraph Agent Graph

Assembles all chatbot nodes into a compiled ``StateGraph`` and exposes it as
the module-level ``chatbot_graph`` used by the chat API endpoint.

Graph topology
--------------

    language_detection
        ↓
    intent_router
        ├── "qa"                       → knowledge_retrieval → response_formatter
        ├── "testimony"/"prayer"/"partnership" → action_flow
        │       ├── (missing fields)   → response_formatter
        │       └── (all slots filled) → confirmation
        │               ├── "confirmed"  → submission → response_formatter
        │               ├── "cancelled"  → response_formatter
        │               └── "awaiting"   → response_formatter
        └── "unknown"                  → fallback → response_formatter
                                                        ↓
                                                       END

References
----------
- Req §7 (LangGraph Agent Graph), all acceptance criteria 7.1–7.6
- Design § "LangGraph Agent Graph" → Mermaid diagram and Node Responsibilities table
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.chatbot.nodes.confirm import confirm_decision_router, confirmation_node
from app.chatbot.nodes.fallback import fallback_node
from app.chatbot.nodes.flow import action_flow_node
from app.chatbot.nodes.formatter import response_formatter_node
from app.chatbot.nodes.knowledge import knowledge_retrieval_node
from app.chatbot.nodes.language import language_detection_node
from app.chatbot.nodes.router import intent_router_node
from app.chatbot.nodes.submit import submission_node
from app.chatbot.session import AgentState


# ---------------------------------------------------------------------------
# Intent routing function — maps intent value to next node name
# ---------------------------------------------------------------------------

def _intent_router(state: AgentState) -> str:
    """
    Conditional edge function: map ``state["intent"]`` to a graph node name.

    Returns
    -------
    str
        One of ``"knowledge_retrieval"``, ``"action_flow"``, ``"fallback"``.
    """
    intent = state.get("intent", "unknown") or "unknown"

    if intent == "qa":
        return "knowledge_retrieval"
    if intent in {"testimony", "prayer", "partnership"}:
        return "action_flow"
    return "fallback"


# ---------------------------------------------------------------------------
# Action flow routing function — check whether all required slots are filled
# ---------------------------------------------------------------------------

def _action_flow_router(state: AgentState) -> str:
    """
    Conditional edge function: decide whether to confirm or continue prompting.

    If ``state["flow_step"] == "awaiting_confirm"``, the user already saw the
    summary and has just replied — route back to confirmation so
    ``confirm_decision_router`` can dispatch to submission or cancellation.

    If ``state["missing_fields"]`` is empty (all slots collected) the graph
    moves to confirmation; otherwise it goes to the response formatter to
    prompt for the next missing field.

    Returns
    -------
    str
        ``"confirmation"`` or ``"response_formatter"``.
    """
    # User replied to the confirmation prompt — re-enter confirmation so
    # confirm_decision_router can dispatch to submission / cancellation.
    if state.get("flow_step") == "awaiting_confirm":
        return "confirmation"

    missing = state.get("missing_fields") or []
    return "confirmation" if not missing else "response_formatter"


# ---------------------------------------------------------------------------
# Build and compile the graph
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("language_detection", language_detection_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("knowledge_retrieval", knowledge_retrieval_node)
    graph.add_node("action_flow", action_flow_node)
    graph.add_node("confirmation", confirmation_node)
    graph.add_node("submission", submission_node)
    graph.add_node("response_formatter", response_formatter_node)
    graph.add_node("fallback", fallback_node)

    # Set entry point
    graph.set_entry_point("language_detection")

    # language_detection → intent_router (always)
    graph.add_edge("language_detection", "intent_router")

    # intent_router → knowledge_retrieval | action_flow | fallback
    graph.add_conditional_edges(
        "intent_router",
        _intent_router,
        {
            "knowledge_retrieval": "knowledge_retrieval",
            "action_flow": "action_flow",
            "fallback": "fallback",
        },
    )

    # action_flow → confirmation | response_formatter
    graph.add_conditional_edges(
        "action_flow",
        _action_flow_router,
        {
            "confirmation": "confirmation",
            "response_formatter": "response_formatter",
        },
    )

    # confirmation → submission | response_formatter (confirmed/cancelled/awaiting)
    graph.add_conditional_edges(
        "confirmation",
        confirm_decision_router,
        {
            "confirmed": "submission",
            "cancelled": "response_formatter",
            "awaiting": "response_formatter",
        },
    )

    # Simple edges
    graph.add_edge("knowledge_retrieval", "response_formatter")
    graph.add_edge("submission", "response_formatter")
    graph.add_edge("fallback", "response_formatter")
    graph.add_edge("response_formatter", END)

    return graph


# ---------------------------------------------------------------------------
# Module-level compiled graph — imported by the chat API endpoint
# ---------------------------------------------------------------------------
chatbot_graph = _build_graph().compile()
