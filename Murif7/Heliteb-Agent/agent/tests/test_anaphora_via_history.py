"""Tests that anaphora ("de la misma línea", "este producto", "estas dos",
"y hay stock?") is resolved by the ReAct loop using the conversation
history (the LLM sees prior ToolMessages), NOT by the old regex-based
resolve_references node (which was deleted in Paso 6 of the migration).

Replaces test_memory_local.py — that file tested the old recent_saps +
resolve_references mechanism. The new agent has no recent_saps/_last_intent
fields in AgentState: memory comes from the messages history preserved
by the LangGraph checkpointer + add_messages reducer.

These tests are integration-style: they invoke agent_graph.invoke with a
sequence of turns on the same thread_id and verify that:
1. Turn 1 ("ficha del DS-2CD1023G0E-I") produces a tool-bearing response.
2. Turn 2 ("y su precio?") on the SAME thread produces a coherent answer
   that references the same product (i.e., the LLM resolved the anaphora
   "su" from the prior AIMessage without needing dedicated memory fields).

NOTE: these tests require network access (Supabase + Mistral). They are
marked with @pytest.mark.skipif(NO_LLM, ...) so they don't fail in CI
without API keys. Use --runslow to force them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Skip all tests in this module if API keys are not configured
NO_LLM = not (
    os.environ.get("SUPABASE_URL")
    and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    and (os.environ.get("MISTRAL_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
)
pytestmark = pytest.mark.skipif(
    NO_LLM,
    reason="Anaphora-via-history tests need Supabase + Mistral/Gemini API keys",
)


@pytest.fixture(scope="module")
def graph():
    """Import agent_graph only once per module run (heavy: loads BGE-M3)."""
    # Make agent/ importable when run from the repo root or from agent/
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    from graph import agent_graph
    return agent_graph


def _new_thread_id() -> str:
    """Generate a unique thread_id per test to avoid state leakage."""
    import uuid
    return f"test-anaphora-{uuid.uuid4().hex[:8]}"


def test_anaphora_su_precio_references_prior_product(graph):
    """Turn 1: "ficha del DS-2CD1023G0E-I". Turn 2: "y su precio?".
    Turn 2 should resolve "su" from the prior ToolMessage and return
    a price for the SAME SAP (DS-2CD1023G0E-I / its SAP), not a generic
    "no encontré" or a different product.
    """
    thread = _new_thread_id()
    cfg = {"configurable": {"thread_id": thread}}

    # Turn 1 — establish product context
    state1 = {
        "messages": [{"role": "user", "content": "ficha técnica del DS-2CD1023G0E-I"}],
        "intent": "",
        "response": "",
        "email_address": "",
    }
    result1 = graph.invoke(state1, cfg)
    assert result1.get("response"), "Turn 1 should produce a response"
    # The response should mention a Hikvision product (DS-2CD1023G0E-I is Hikvision)
    resp1 = result1["response"]
    assert "Hikvision" in resp1 or "DS-2CD" in resp1, f"Turn 1 response should mention Hikvision/DS-2CD, got: {resp1[:200]}"

    # Turn 2 — anaphora "su precio" (no SAP, no model — must reference turn 1 product)
    state2 = {
        "messages": [{"role": "user", "content": "y su precio?"}],
        "intent": "",
        "response": "",
        "email_address": "",
    }
    result2 = graph.invoke(state2, cfg)
    resp2 = result2.get("response", "")
    assert resp2, "Turn 2 should produce a response"
    # The response should mention COP price — the anaphora was resolved
    assert "COP" in resp2 or "$" in resp2, (
        f"Turn 2 'y su precio?' should produce a COP price via anaphora resolution, got: {resp2[:300]}"
    )


def test_anaphora_hay_stock_references_prior_product(graph):
    """Turn 1: "DS-2CD1023G0E-I". Turn 2: "hay stock en Bogotá?".
    Turn 2 should resolve "stock" question against the SAP from turn 1
    (without the user repeating the SAP), and either list stock or say
    the specific product has no stock — not ask "which product?".
    """
    thread = _new_thread_id()
    cfg = {"configurable": {"thread_id": thread}}

    state1 = {
        "messages": [{"role": "user", "content": "quiero información del DS-2CD1023G0E-I"}],
        "intent": "",
        "response": "",
        "email_address": "",
    }
    result1 = graph.invoke(state1, cfg)
    assert result1.get("response")

    state2 = {
        "messages": [{"role": "user", "content": "hay stock en Bogotá?"}],
        "intent": "",
        "response": "",
        "email_address": "",
    }
    result2 = graph.invoke(state2, cfg)
    resp2 = result2.get("response", "")
    # Either stock is mentioned with bodega name, or the agent says no stock
    # — but it should NOT ask "qué producto?" (which would indicate anaphora
    # resolution failed)
    assert ("Bogot" in resp2 or "stock" in resp2.lower() or "unidades" in resp2.lower()
            or "no hay" in resp2.lower()), (
        f"Turn 2 should resolve anaphora and answer stock — got: {resp2[:300]}"
    )
    assert "qué producto" not in resp2.lower() and "cuál producto" not in resp2.lower(), (
        f"Turn 2 should NOT ask 'qué producto?' — anaphora should be resolved. Got: {resp2[:300]}"
    )


def test_agent_state_has_no_recent_saps_fields(graph):
    """The new AgentState should NOT have recent_saps / recent_linea /
    recent_categoria / recent_marca / last_intent / resolved_context fields
    (those were deleted in Paso 6).代理人
    """
    # We can't introspect TypedDict field names directly (they're just a dict
    # at runtime), so we verify by invoking and checking the returned state
    # doesn't contain those keys.
    thread = _new_thread_id()
    cfg = {"configurable": {"thread_id": thread}}
    state = {
        "messages": [{"role": "user", "content": "hola"}],
        "intent": "",
        "response": "",
        "email_address": "",
    }
    result = graph.invoke(state, cfg)
    # Legacy memory fields should be ABSENT from the result (not just empty)
    assert "recent_saps" not in result, "AgentState should not have recent_saps (deleted in Paso 6)"
    assert "recent_linea" not in result, "AgentState should not have recent_linea"
    assert "recent_categoria" not in result, "AgentState should not have recent_categoria"
    assert "recent_marca" not in result, "AgentState should not have recent_marca"
    assert "last_intent" not in result, "AgentState should not have last_intent"
    assert "resolved_context" not in result, "AgentState should not have resolved_context"
    # But the preserved legacy fields should be present
    assert "response" in result
    assert "intent" in result