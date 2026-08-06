"""Script de prueba local para evaluar memoria conversacional del agente.

Ejecuta una conversacion multi-turno y verifica que:
1. El agente recuerda SAPs mencionados (recent_saps)
2. "de la misma linea" resuelve a la linea del producto anterior
3. "estas dos" resuelve a los 2 ultimos SAPs
4. "este producto" resuelve al ultimo SAP

Uso:
    cd Agente-Heliteb/agent
    python test_memory_local.py

Requiere: .env con SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, MISTRAL_API_KEY
"""
import os
import sys

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from graph import agent_graph, resolve_references, execute_tool, AgentState

THREAD_ID = "test-memory-local"
config = {"configurable": {"thread_id": THREAD_ID}}

def print_separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def print_state_snapshot(state: dict, turn: int):
    """Imprime el estado relevante despues de cada turno."""
    print(f"\n--- Turno {turn} -- Estado ---")
    print(f"  intent:        {state.get('intent', '?')}")
    resp = state.get('response') or ''
    print(f"  response:      {resp[:120]}...")
    print(f"  recent_saps:   {state.get('recent_saps', [])}")
    print(f"  recent_linea:  {state.get('recent_linea', '')}")
    print(f"  recent_cat:    {state.get('recent_categoria', '')}")
    print(f"  recent_marca:  {state.get('recent_marca', '')}")
    print(f"  last_intent:   {state.get('last_intent', '')}")
    resolved = state.get('resolved_context', {})
    print(f"  resolved_saps:  {resolved.get('resolved_saps', [])}")
    print(f"  resolved_filt: {resolved.get('resolved_filters', {})}")
    msgs = state.get("messages", [])
    print(f"  messages count: {len(msgs)}")
    for m in msgs[-3:]:
        role = m.get("role", "?") if isinstance(m, dict) else "?"
        content = str(m.get("content", ""))[:80] if isinstance(m, dict) else str(m)[:80]
        print(f"    [{role}] {content}...")

def run_turn(message: str, turn: int) -> dict:
    """Ejecuta un turno de conversacion y retorna el estado resultante."""
    print_separator(f"TURNO {turn}: \"{message}\"")

    state = {
        "messages": [{"role": "user", "content": message}],
        "intent": "",
        "tool_result": "",
        "response": "",
        "email_address": "",
    }

    result = agent_graph.invoke(state, config)
    print_state_snapshot(result, turn)

    response = result.get("response", "")
    print(f"\n  RESPUESTA COMPLETA:")
    print(f"  {response[:500]}")
    return result

def test_resolve_references_isolated():
    """Prueba unitaria de resolve_references sin LLM ni Supabase."""
    print_separator("PRUEBA UNITARIA: resolve_references (sin LLM)")

    # Simular estado con memoria previa
    state: AgentState = {
        "messages": [{"role": "user", "content": "de la misma linea"}],
        "intent": "specs",
        "tool_result": "",
        "response": "",
        "email_address": "",
        "quotation_saps": "",
        "quotation_description": "",
        "recent_saps": ["311315990", "311315672"],
        "recent_linea": "Value Series",
        "recent_categoria": "Cameras",
        "recent_marca": "Hikvision",
        "last_intent": "specs",
        "resolved_context": {},
    }

    result = resolve_references(state)

    print(f"\n  Input: 'de la misma linea'")
    print(f"  recent_linea: {state['recent_linea']}")
    print(f"  resolved_filters: {result['resolved_context']['resolved_filters']}")
    assert result["resolved_context"]["resolved_filters"].get("linea") == "Value Series", \
        f"Expected linea=Value Series, got {result['resolved_context']['resolved_filters']}"
    print("  [PASS] 'de la misma linea' -> linea=Value Series")

    # Test "estas dos"
    state2: AgentState = {**state, "messages": [{"role": "user", "content": "compara estas dos"}]}
    state2["resolved_context"] = {}
    result2 = resolve_references(state2)
    print(f"\n  Input: 'compara estas dos'")
    print(f"  recent_saps: {state2['recent_saps']}")
    print(f"  resolved_saps: {result2['resolved_context']['resolved_saps']}")
    assert result2["resolved_context"]["resolved_saps"] == ["311315990", "311315672"], \
        f"Expected [311315990, 311315672], got {result2['resolved_context']['resolved_saps']}"
    print("  [PASS] 'estas dos' -> [311315990, 311315672]")

    # Test "este producto"
    state3: AgentState = {**state, "messages": [{"role": "user", "content": "dame el precio de este producto"}]}
    state3["resolved_context"] = {}
    result3 = resolve_references(state3)
    print(f"\n  Input: 'precio de este producto'")
    print(f"  recent_saps: {state3['recent_saps']}")
    print(f"  resolved_saps: {result3['resolved_context']['resolved_saps']}")
    assert result3["resolved_context"]["resolved_saps"] == ["311315672"], \
        f"Expected [311315672], got {result3['resolved_context']['resolved_saps']}"
    print("  [PASS] 'este producto' -> [311315672]")

    # Test sin memoria (fresh start)
    state4: AgentState = {
        "messages": [{"role": "user", "content": "de la misma linea"}],
        "intent": "specs", "tool_result": "", "response": "", "email_address": "",
        "quotation_saps": "", "quotation_description": "",
        "recent_saps": [], "recent_linea": "", "recent_categoria": "",
        "recent_marca": "", "last_intent": "", "resolved_context": {},
    }
    result4 = resolve_references(state4)
    print(f"\n  Input: 'de la misma linea' (sin memoria)")
    print(f"  resolved: {result4['resolved_context']}")
    assert not result4["resolved_context"]["resolved_saps"], "Should be empty"
    assert not result4["resolved_context"]["resolved_filters"], "Should be empty"
    print("  [PASS] sin memoria -> resolved_context vacio (no crash)")

def test_full_conversation():
    """Prueba la conversacion completa que fallaba antes."""
    print_separator("CONVERSACION COMPLETA (con LLM + Supabase)")
    print("  Simulando: 311315990 -> 'de la misma linea' -> 'este producto'")
    print("  (Si no hay LLM/Supabase, los pasos fallaran pero resolve_references se prueba)")

    try:
        # Turno 1: producto especifico
        r1 = run_turn("que ventajas tiene 311315990", 1)

        # Turno 2: referencia anaforica
        r2 = run_turn("de la misma linea", 2)

        # Verificar que resolve_references funciono
        resolved2 = r2.get("resolved_context", {})
        if resolved2.get("resolved_filters", {}).get("linea"):
            print(f"\n  [PASS] Turno 2: resolved linea = {resolved2['resolved_filters']['linea']}")
        else:
            print(f"\n  [WARN] Turno 2: no se resolvio linea (recent_linea vacio?)")
            print(f"     recent_linea = {r2.get('recent_linea', '')}")

        # Turno 3: referencia a "este producto"
        r3 = run_turn("dame el precio de este producto", 3)

        resolved3 = r3.get("resolved_context", {})
        if resolved3.get("resolved_saps"):
            print(f"\n  [PASS] Turno 3: resolved_saps = {resolved3['resolved_saps']}")
        else:
            print(f"\n  [WARN] Turno 3: no se resolvio SAP (recent_saps vacio?)")
            print(f"     recent_saps = {r3.get('recent_saps', [])}")

        # Turno 4: "estas dos"
        r4 = run_turn("compara estas dos", 4)

        resolved4 = r4.get("resolved_context", {})
        if resolved4.get("resolved_saps") and len(resolved4["resolved_saps"]) >= 2:
            print(f"\n  [PASS] Turno 4: resolved_saps = {resolved4['resolved_saps']}")
        else:
            print(f"\n  [WARN] Turno 4: no se resolvieron 2 SAPs")
            print(f"     recent_saps = {r4.get('recent_saps', [])}")

    except Exception as e:
        print(f"\n  [ERROR] Error en conversacion: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=" * 60)
    print("  PRUEBA LOCAL: Memoria Conversacional Agente HELITEB")
    print("=" * 60)

    # 1. Pruebas unitarias (sin LLM ni Supabase)
    test_resolve_references_isolated()

    # 2. Conversacion completa (con LLM + Supabase)
    test_full_conversation()

    print_separator("FIN")
    print("  Revisa los resultados arriba.")
    print("  [PASS] = comportamiento correcto")
    print("  [WARN] = verificar (posible falta de datos en Supabase)")
    print("  [ERROR] = error")

if __name__ == "__main__":
    main()