import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage
from healthcare.nodes import triage_node, researcher_node, lifestyle_node, general_node, router
from typing import TypedDict, List, Annotated
import operator

class HealthCareState(TypedDict):
    messages: List
    intent: str
    response: str

def create_graph():
    graph = StateGraph(HealthCareState)
    graph.add_node("triage", triage_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("lifestyle", lifestyle_node)
    graph.add_node("general", general_node)
    graph.set_entry_point("triage")
    graph.add_conditional_edges("triage", router, {
        "end": END, "researcher": "researcher",
        "lifestyle": "lifestyle", "general": "general"
    })
    graph.add_edge("researcher", END)
    graph.add_edge("lifestyle", END)
    graph.add_edge("general", END)
    return graph.compile()


APP_GRAPH = create_graph()

def chat(message: str, history: list = []) -> str:
    try:
        # Convert DB history into alternating user/assistant messages.
        messages = []
        for h in history:
            user_message = (h.get("message") or "").strip()
            ai_message = (h.get("response") or "").strip()
            if user_message:
                messages.append(HumanMessage(content=user_message))
            if ai_message:
                messages.append(AIMessage(content=ai_message))
        messages.append(HumanMessage(content=message))
        
        result = APP_GRAPH.invoke({
            "messages": messages,
            "intent": "",
            "response": ""
        })
        return result.get("response", "Sorry I could not process your request.")
    except Exception as e:
        import traceback
        print("ERROR in chat function:", traceback.format_exc())
        return f"I am having trouble. Please try again. ({str(e)[:100]})"
