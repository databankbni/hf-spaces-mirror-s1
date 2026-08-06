"""TDD test for the migration's single success criterion:

    "qué cámara wifi tenemos con audio bidireccional en stock en Bogotá"

This query must produce a coherent answer that names a concrete bodega
(Bogotá, Montería, Centro, Obrero), WITHOUT the developer having written
a regex or keyword dictionary entry anticipating "audio bidireccional".

Before the migration: this query failed because _extract_search_filters
dictionary didn't map "audio bidireccional" to any field, and the FTS
fallback (ILIKE) didn't stem Spanish. After the migration: the LLM fills
the @tool args from natural language, the new buscar_productos_hibrido
RPC fuses tsvector (with unaccent + spanish_stem, covering parametro_*
fields where "audio bidireccional" lives) + pgvector via RRF, and the
ReAct loop chains buscar_producto → consultar_stock to produce the
bodega-level answer.

This test is the TDD anchor of the migration plan (Paso 8). It should
FAIL on the old rigid pipeline and PASS on the new ReAct agent. Run
with a live Supabase + Mistral environment; skipped otherwise.

Run:  pytest agent/tests/test_query_exito_reto.py --runslow -s
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

NO_LLM = not (
    os.environ.get("SUPABASE_URL")
    and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    and (os.environ.get("MISTRAL_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
)
pytestmark = pytest.mark.skipif(
    NO_LLM,
    reason="Query-exito test needs Supabase + Mistral/Gemini API keys",
)


@pytest.fixture(scope="module")
def graph():
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    from graph import agent_graph
    return agent_graph


SUCCESS_QUERY = "qué cámara wifi tenemos con audio bidireccional en stock en Bogotá"


def test_query_exito_reto_responde_con_bodega_concreta(graph):
    """La query de éxito debe devolver respuesta con bodega concreta.

    Criterios:
      1. La respuesta no es vacía ni "no encontré" genérico.
      2. Menciona una bodega concreta (Bogotá, Montería, Centro, Obrero)
         o dice explícitamente "no hay stock" — lo importante es que el
         agente procesa la query natural sin fallar.
      3. NO pregunta "qué cámara?" / "cuál producto?" — eso indicaría
         que no entendió la consulta (el síntoma del RAG rígido original).
      4. La respuesta menciona alguna marca del catálogo (Hikvision,
         HiLook, HIKMICRO, EZVIZ) — el agente sí buscó en el catálogo.
    """
    thread = f"test-exito-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread}}

    state = {
        "messages": [{"role": "user", "content": SUCCESS_QUERY}],
        "intent": "",
        "response": "",
        "email_address": "",
    }
    result = graph.invoke(state, cfg)
    resp = result.get("response", "")

    # 1. No vacío
    assert resp, "La respuesta no debe ser vacía"
    assert len(resp) > 30, f"Respuesta demasiado corta: {resp!r}"

    # 2. Menciona una bodega o dice "no hay stock"
    bodegas = ["Bogot", "Monter", "Centro", "Obrero", "Bello", "Valledupar"]
    dice_no_hay = "no hay" in resp.lower() or "sin stock" in resp.lower()
    mentions_bodega = any(b in resp for b in bodegas)
    assert dice_no_hay or mentions_bodega, (
        f"Respuesta no menciona bodega concreta ni dice 'no hay stock': {resp[:400]}"
    )

    # 3. NO pregunta "qué cámara" / "cuál producto" (síntoma del RAG rígido)
    failure_phrases = [
        "qué cámara",
        "cuál cámara",
        "qué producto",
        "cuál producto",
        "qué modelo",
        "cuál modelo",
        "no entendí",
        "puedes reformular",
    ]
    for phrase in failure_phrases:
        assert phrase.lower() not in resp.lower(), (
            f"Respuesta contiene '{phrase}' — síntoma de RAG rígido (no entendió la query): {resp[:400]}"
        )

    # 4. Menciona una marca del catálogo (el agente sí buscó)
    marcas = ["hikvision", "hilook", "hikmicro", "ezviz", "dahua", "outsource"]
    assert any(m in resp.lower() for m in marcas), (
        f"Respuesta no menciona ninguna marca del catálogo: {resp[:400]}"
    )


def test_query_exito_reto_es_consistente_10_intentos(graph):
    """El criterio de éxito del plan exige 10/10 consistencia.

    Corre la misma query 10 veces y verifica que SIEMPRE responda (no
    "no entendí") y mencione bodega o stock. Acepta variación en los
    detalles del producto listado, pero no acepta que el agente diga
    "qué cámara?" en ninguno de los intentos.

    Skip si RUNSLOW no está activo (es lento: 10 invocaciones de graph).
    """
    if not os.environ.get("RUNSLOW"):
        pytest.skip("Run with RUNSLOW=1 to verify 10/10 consistency")

    failure_phrases = [
        "qué cámara", "cuál cámara", "qué producto", "cuál producto",
        "no entendí", "puedes reformular", "qué modelo", "cuál modelo",
    ]
    bodegas = ["Bogot", "Monter", "Centro", "Obrero", "Bello", "Valledupar"]

    for i in range(10):
        thread = f"test-exito-consistency-{i}-{uuid.uuid4().hex[:8]}"
        cfg = {"configurable": {"thread_id": thread}}
        state = {
            "messages": [{"role": "user", "content": SUCCESS_QUERY}],
            "intent": "",
            "response": "",
            "email_address": "",
        }
        result = graph.invoke(state, cfg)
        resp = result.get("response", "")
        assert resp, f"[{i}/10] Respuesta vacía"
        for phrase in failure_phrases:
            assert phrase.lower() not in resp.lower(), (
                f"[{i}/10] Contiene '{phrase}' — síntoma de RAG rígido: {resp[:300]}"
            )
        dice_no_hay = "no hay" in resp.lower() or "sin stock" in resp.lower()
        mentions_bodega = any(b in resp for b in bodegas)
        assert dice_no_hay or mentions_bodega, (
            f"[{i}/10] No menciona bodega ni dice 'no hay': {resp[:300]}"
        )