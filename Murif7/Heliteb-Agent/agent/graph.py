"""LangGraph ReAct agent for HELITEB commercial advisor.

Flujo:
    START → scope_tools_by_intent → agent_node
                                          ↓ (conditional)
                              tools_node ← tool_calls? → post_tools → END
                                  ↓
                              agent_node (loop, max MAX_TURNS=4)

El agente usa ``bind_tools`` dinámico sobre un subconjunto de las 5 tools
(acotado por el scope detectado) y delega el razonamiento ReAct al LLM
con Mistral Large. ToolNode ejecuta solo las tool_calls que el LLM emite.
"""
import logging
import re
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from tools.catalog import buscar_producto, ficha_producto
from tools.stock import consultar_stock
from tools.cross_sell import sugerir_complementos
from tools.quotations import generar_cotizacion
from llm.client import get_llm
from prompts.system import SYSTEM_PROMPT
from db.supabase import search_variants_by_model_prefix


logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

MAX_TURNS = 4  # Maximum agent_node invocations per query


# Tool registry — name → @tool-decorated object
TOOL_REGISTRY: dict[str, Any] = {
    "buscar_producto": buscar_producto,
    "ficha_producto": ficha_producto,
    "consultar_stock": consultar_stock,
    "sugerir_complementos": sugerir_complementos,
    "generar_cotizacion": generar_cotizacion,
}


# Static mapping: scope → tools subset to bind
_SCOPE_TO_TOOLS: dict[str, list[str]] = {
    "greeting": [],
    "product_query": ["buscar_producto", "ficha_producto"],
    "stock": ["buscar_producto", "consultar_stock"],
    "compare": ["buscar_producto", "ficha_producto"],
    "cross_sell": ["buscar_producto", "sugerir_complementos"],
    "quotation": ["buscar_producto", "generar_cotizacion"],
    "other": [],
}


# Static mapping: scope → legacy intent (compat con main.py y tests)
_SCOPE_TO_LEGACY_INTENT: dict[str, str] = {
    "greeting": "greeting",
    "product_query": "specs",  # default; agent_node lo sobreescribe a "price" si detecta
    "stock": "stock",
    "compare": "compare_products",
    "cross_sell": "cross_sell",
    "quotation": "quotation",
    "other": "other",
}


# Price detection: si el mensaje matchea esto, el intent legacy será "price"
_PRICE_RE = re.compile(
    r'\b(precio|valor|cu[aá]nto\s+(?:cuesta|vale|es)|cuesta|vale|costo|'
    r'tarifa|cu[aá]nto)\b',
    re.IGNORECASE,
)


# ── Pydantic schema for scope_tools_by_intent ───────────────────────────────


class ScopeToolsSchema(BaseModel):
    """Validates the LLM's tool-scope decision."""
    scope: Literal[
        "greeting", "product_query", "stock", "compare",
        "cross_sell", "quotation", "other"
    ]
    tools_subset: list[str] = Field(default_factory=list)
    needs_user_input: bool = False


SCOPE_TOOLS_PROMPT = """Eres un clasificador para un agente comercial de HELITEB.

Tu ÚNICO trabajo es analizar la consulta del asesor y devolver:
  - scope: una de las 7 categorías (ver abajo)
  - tools_subset: lista de herramientas necesarias (subconjunto de las 5 disponibles)
  - needs_user_input: true si faltan datos obligatorios (SAPs, nombre cliente) y hay que preguntar

SCOPES (elige UNO):
  • greeting — solo saludos, despedidas o charla de cortesía
  • product_query — specs, ficha técnica, precios, características, modelos, recomendaciones
  • stock — disponibilidad, inventario, existencias, en qué bodega hay
  • compare — comparar 2 o más productos del catálogo
  • cross_sell — accesorios, complementos, venta cruzada para un producto
  • quotation — cotización formal, proforma, PDF, presupuesto (puede incluir email)
  • other — todo lo demás (preguntas generales, dudas no comerciales)

HERRAMIENTAS (elige solo las que NECESITES):
  - buscar_producto: búsqueda híbrida en catálogo
  - ficha_producto: ficha técnica de un producto por SAP
  - consultar_stock: disponibilidad por bodega (requiere SAP)
  - sugerir_complementos: accesorios para un producto (requiere SAP)
  - generar_cotizacion: genera PDF de cotización (requiere SAPs y nombre)

REGLAS:
- Si scope es 'greeting' u 'other', tools_subset debe ser [].
- Para 'quotation' incluye 'generar_cotizacion' SIEMPRE.
- Responde SOLO con el JSON estructurado, sin explicaciones."""


# ── regex fallback for scope detection ─────────────────────────────────────


_PRODUCT_QUERY_RE = re.compile(
    r'\b(?:dame|dime|mu[eé]strame|busca|encuentra|lista|'
    r'productos?|referencias?|modelos?|art[ií]culos?|equipos?|'
    r'l[ií]nea|l[ií]neas|categor[ií]a|marca|baratos?|econ[oó]micos?)\b',
    re.IGNORECASE,
)


def _is_pure_greeting(msg: str) -> bool:
    """True if the message is ONLY a greeting, not a product query."""
    return bool(re.fullmatch(
        r'\s*(hola|buenas?|saludos|buenos?\s+d[ií]as?|'
        r'buenas?\s+tardes?|buenas?\s+noches?|'
        r'hi|hello|hey|qu[eé]\s+tal|'
        r'c[oó]mo\s+(?:est[aá]s?|va|andas)).*',
        msg, re.IGNORECASE,
    ))


def _regex_scope(text: str) -> ScopeToolsSchema:
    """Deterministic regex-based scope detection (fallback del LLM)."""
    low = text.lower().strip()

    if re.search(r'^(hola|buenas?|saludos|buenos d|buenas t|buenas n|hi|hello)', low):
        return ScopeToolsSchema(scope="greeting", tools_subset=[], needs_user_input=False)
    if re.search(r'\b(cotiz|cotizacion|proforma|presupuesto|pdf)\b', low):
        return ScopeToolsSchema(
            scope="quotation",
            tools_subset=["buscar_producto", "generar_cotizacion"],
            needs_user_input=True,
        )
    if re.search(r'\b(compar|diferencia|vs|versus)\b', low):
        return ScopeToolsSchema(
            scope="compare",
            tools_subset=["buscar_producto", "ficha_producto"],
            needs_user_input=True,
        )
    if re.search(r'\b(stock|inventario|disponibil|existencia|bodega)\b', low):
        return ScopeToolsSchema(
            scope="stock",
            tools_subset=["buscar_producto", "consultar_stock"],
            needs_user_input=False,
        )
    if re.search(r'\b(complement|accesori|que mas necesit)\b', low):
        return ScopeToolsSchema(
            scope="cross_sell",
            tools_subset=["buscar_producto", "sugerir_complementos"],
            needs_user_input=True,
        )
    if re.search(
        r'\b(especif|ficha|caracterist|modelo|camara|nvr|dvr|'
        r'precio|valor|cuanto|cuesta|vale|recomiend|suger)\b',
        low,
    ):
        return ScopeToolsSchema(
            scope="product_query",
            tools_subset=["buscar_producto", "ficha_producto"],
            needs_user_input=False,
        )
    # installation removido del repo → scope="other"
    return ScopeToolsSchema(scope="other", tools_subset=[], needs_user_input=False)


# ── AgentState ──────────────────────────────────────────────────────────────


class AgentState(TypedDict, total=False):
    """Estado del agente ReAct LangGraph con memoria conversacional.

    ``messages`` usa ``add_messages`` reducer para acumulación automática
    desde el checkpoint. El resto de campos son opcionales (``total=False``)
    y se leen con ``.get()``.
    """
    messages: Annotated[list, add_messages]
    intent: str
    response: str
    email_address: str
    quotation_saps: str
    quotation_description: str
    tools_scope: dict
    turn_count: int


# ── node: scope_tools_by_intent ─────────────────────────────────────────────


def scope_tools_by_intent(state: AgentState) -> AgentState:
    """Decide el scope y tools_subset para la consulta actual.

    Usa LLM con structured output (Pydantic ``ScopeToolsSchema``) y cae a
    regex si el LLM falla. Setea ``state["intent"]`` con valor legacy para
    compatibilidad con ``main.py`` y tests.
    """
    user_msg = _msg_content(state["messages"][-1])
    low = user_msg.lower()

    # ── LLM classification with regex fallback ───────────────────────
    scope_result: ScopeToolsSchema
    try:
        llm = get_llm("simple")
        structured_llm = llm.with_structured_output(ScopeToolsSchema)
        scope_result = structured_llm.invoke([
            {"role": "system", "content": SCOPE_TOOLS_PROMPT},
            {"role": "user", "content": user_msg},
        ])
    except Exception:
        logger.info("LLM scope classification failed, falling back to regex")
        scope_result = _regex_scope(user_msg)

    # ── Re-classification guard: regex/LLM often says "greeting" or "other"
    #    for product queries. The ``_PRODUCT_QUERY_RE`` catches "busca",
    #    "dame", "cámara", "modelo", etc. ──
    if scope_result.scope in ("other", "greeting"):
        if _PRODUCT_QUERY_RE.search(low) and not _is_pure_greeting(low):
            scope_result = ScopeToolsSchema(
                scope="product_query",
                tools_subset=_SCOPE_TO_TOOLS["product_query"],
                needs_user_input=False,
            )

    # ── Validate tools_subset against static mapping (defensive) ─────
    scope = scope_result.scope
    allowed = _SCOPE_TO_TOOLS.get(scope, [])
    if scope in ("greeting", "other"):
        tools_subset: list[str] = []
    else:
        # Keep only tools known to the registry AND in the static mapping
        tools_subset = [t for t in scope_result.tools_subset if t in TOOL_REGISTRY and t in allowed]
        if not tools_subset:
            tools_subset = allowed  # fallback to static mapping

    # ── Set state ────────────────────────────────────────────────────
    state["tools_scope"] = {
        "scope": scope,
        "tools_subset": tools_subset,
        "needs_user_input": scope_result.needs_user_input,
    }

    # Map scope → legacy intent (con distinción price/specs para product_query)
    if scope == "product_query" and _PRICE_RE.search(low):
        state["intent"] = "price"
    else:
        state["intent"] = _SCOPE_TO_LEGACY_INTENT.get(scope, "other")

    # ── Reset turn_count para el nuevo turno ────────────────────────
    # CRÍTICO: el ``MemorySaver`` checkpointer preserva ``turn_count`` del
    # turno anterior entre invocaciones con el mismo ``session_id``. Si el
    # turno 1 termina con turn_count=3, el turno 2 empieza con turn_count=3
    # y ``_route_after_agent`` dispara MAX_TURNS=4 en la primera iteración
    # del loop ReAct → corta sin ejecutar tools. scope_tools_by_intent es el
    # entry point de cada query nueva, así que aquí reseteamos.
    state["turn_count"] = 0

    return state


# ── node: agent_node ────────────────────────────────────────────────────────


REACT_INSTRUCTIONS = f"""Eres un agente ReAct con herramientas. Reglas operativas:

1. QUERY CORTA para buscar_producto (CRÍTICO):
   Pasa a buscar_producto una query CORTA de máximo 8-10 palabras, no concatenes todos los sinónimos.
   El catálogo usa tsvector con AND logic — si pasas 20+ términos, NINGÚN producto los tiene todos y devuelve 0.
   Ejemplos的正确os:
     • "cámara wifi audio bidireccional" (5 palabras) ✓
     • "cámara exterior IP67 visión nocturna" (5 palabras) ✓
     • "cámara wifi night vision color" (5 palabras) ✓
   Ejemplo INCORRECTO:
     • "cámara WiFi wireless inalámbrico audio bidireccional two-way micrófono exterior IP67 impermeable visión nocturna IR ColorVu PT app móvil detección personas IA alerta móvil" (25+ términos) ✗ → devuelve 0

2. SINONIMIZACIÓN conceptual (traducir 2-3 términos clave, no todos):
   "lluvia/sol/agua/exterior" → "exterior IP67"
   "sin cables/inalámbrica" → "WiFi"
   "noche/baja luz" → "visión nocturna" o "ColorVu"
   "móvil/celular/app" → "PT app"
   "nube/sin disco" → "WiFi cloud"
   "audio" → "audio bidireccional"
   Elige los 2-3 sinónimos más relevantes para la query del asesor. NO los concatenes todos.

3. ENCADENA tools:
   - scope=stock: tras buscar_producto, SIEMPRE llama consultar_stock con cada SAP devuelto antes de responder.
   - scope=quotation: tras buscar_producto, pide al asesor nombre cliente ANTES de llamar generar_cotizacion.

4. PRESENTA 3-5 OPCIONES cuando buscar_producto devuelva múltiples resultados.

5. SEGUNDA BÚSQUEDA si la primera devuelve vacío:
   Si buscar_producto dice "No encontré", NO respondas igual. Prueba con términos MÁS SIMPLES
   (ej: "cámara wifi" en lugar de "cámara wifi audio bidireccional exterior IP67").
   Solo di "no encontré" si tras el segundo intento sigue vacío.

6. EZVIZ: es la ÚNICA marca WiFi del catálogo. Si el asesor pregunta por "wifi" o "sin cables",
   EZVIZ debe aparecer. NO te quedes solo con HIKVISION.

7. Máximo {MAX_TURNS} turnos. Si lo encontraste, responde texto plano (sin tool_calls). Si no, dilo honesto."""


def _call_llm_with_fallback(llm, messages, tools_to_bind=None, tool_choice=None):
    """Invoke LLM con fallback a Gemini (get_llm("fallback")) on 429 rate limit.

    Si Mistral devuelve 429 o rate_limit, reintenta con Gemini 2.5 Flash.
    Si ``tools_to_bind`` se pasa, replica el bind_tools sobre el fallback;
    si además ``tool_choice`` estaba forzado ("required"), lo replica como
    ``tool_choice="required"`` (formato compatible con Gemini).
    """
    try:
        return llm.invoke(messages)
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "rate_limit" in msg.lower() or "rate limit" in msg.lower():
            logger.warning("Mistral rate-limited (429), retrying with Gemini fallback")
            fallback_llm = get_llm("fallback")
            if tools_to_bind:
                if tool_choice:
                    fallback_llm_b = fallback_llm.bind_tools(
                        tools_to_bind, tool_choice="required",
                    )
                else:
                    fallback_llm_b = fallback_llm.bind_tools(tools_to_bind)
                return fallback_llm_b.invoke(messages)
            return fallback_llm.invoke(messages)
        raise


def _build_agent_context_messages(state_messages: list) -> list:
    """Filtra el historial de mensajes para enviar al LLM solo contexto relevante.

    Turno actual: incluye TODOS los mensajes (HumanMessage, AIMessage, ToolMessage)
    — estos son necesarios para el razonamiento ReAct del loop actual.

    Turnos anteriores: SOLO HumanMessage y AIMessage SIN tool_calls
    (es decir, las preguntas del asesor y las respuestas finales del agente).
    Omite ToolMessages intermedios y AIMessages con tool_calls del turno
    anterior — esto: (a) ahorra tokens, (b) evita que Mistral reemita los
    mismos tool_calls basándose en lo que vio antes, y (c) mitiga el bug de
    que el agente repita la respuesta del turno anterior.

    Mantiene orden cronológico.
    """
    # Encontrar el índice del último HumanMessage (inicio del turno actual)
    current_start = 0
    for i in range(len(state_messages) - 1, -1, -1):
        m = state_messages[i]
        if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") == "user"):
            current_start = i
            break

    result = []
    for i, m in enumerate(state_messages):
        if i < current_start:
            # Turno anterior: solo HumanMessage y AIMessage sin tool_calls
            if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") == "user"):
                result.append(m)
            elif isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
                result.append(m)
            # ToolMessages y AIMessage con tool_calls del turno anterior: omitir
        else:
            # Turno actual: incluir todo
            result.append(m)
    return result


def agent_node(state: AgentState) -> dict:
    """LLM con ``bind_tools`` dinámico según ``state['tools_scope']``.

    - greeting/other (sin tools): fast-path o LLM sin tools.
    - quotation con email: pre-set state + forzar tool_choice="required".
    - Resto: ``bind_tools(tools_subset)`` estándar.
    """
    scope = state.get("tools_scope", {}).get("scope", "other")
    tools_subset = state.get("tools_scope", {}).get("tools_subset", [])
    turn_count = state.get("turn_count", 0)

    # ── Fast-path: greeting (no LLM) ─────────────────────────────────
    if scope == "greeting":
        return {
            "response": _greeting_response(),
            "turn_count": turn_count + 1,
        }

    # ── Build tool objects from subset ──────────────────────────────
    tools_to_bind = [TOOL_REGISTRY[name] for name in tools_subset if name in TOOL_REGISTRY]

    # ── No tools: simple LLM, sin bind_tools ─────────────────────────
    if not tools_to_bind:
        llm = get_llm("simple")
        ai_msg = _call_llm_with_fallback(llm, [
            SystemMessage(content=SYSTEM_PROMPT),
            *_build_agent_context_messages(state["messages"]),
        ])
        return {
            "messages": [ai_msg],
            "turn_count": turn_count + 1,
        }

    # ── Quotation + email detected: pre-set state and force tool ────
    # Solo en la primera entrada al nodo (turn_count==0) para no loop infinito
    if scope == "quotation" and turn_count == 0:
        last_human = _last_human_message(state["messages"])
        if last_human:
            user_text = _msg_content(last_human)
            email = _extract_email(user_text)
            if email:
                updates: dict[str, Any] = {
                    "email_address": email,
                    "turn_count": turn_count + 1,
                }
                saps = re.findall(r'\b\d{9}\b', user_text)
                if saps:
                    updates["quotation_saps"] = ",".join(saps)
                desc = user_text.strip()
                if desc:
                    updates["quotation_description"] = desc

                # Force tool_choice="required" — el LLM DEBE llamar la tool
                # (el envío de email es irreversible; no queremos respuesta de texto)
                tools_q = [TOOL_REGISTRY["generar_cotizacion"]]
                llm = get_llm("complex").bind_tools(
                    tools_q,
                    tool_choice="required",
                )
                ai_msg = _call_llm_with_fallback(
                    llm,
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        SystemMessage(content=REACT_INSTRUCTIONS),
                        *_build_agent_context_messages(state["messages"]),
                    ],
                    tools_to_bind=tools_q,
                    tool_choice="required",
                )
                updates["messages"] = [ai_msg]
                return updates

    # ── Standard case: bind_tools(subset) ────────────────────────────
    # Forzar tool_choice="required" en la primera iteración (turn_count==0)
    # para que Mistral arranque emitiendo un tool_call en vez de responder con
    # texto plano y cortar el loop ReAct antes de que se ejecute ninguna tool.
    # En iteraciones siguientes, permitir al LLM decidir si ya encontró la
    # respuesta final (sin tool_calls) o si necesita otra tool.
    if turn_count == 0:
        llm = get_llm("complex").bind_tools(tools_to_bind, tool_choice="required")
    else:
        llm = get_llm("complex").bind_tools(tools_to_bind)
    ai_msg = _call_llm_with_fallback(
        llm,
        [
            SystemMessage(content=SYSTEM_PROMPT),
            SystemMessage(content=REACT_INSTRUCTIONS),
            *_build_agent_context_messages(state["messages"]),
        ],
        tools_to_bind=tools_to_bind,
        tool_choice=("required" if turn_count == 0 else None),
    )

    new_turn = turn_count + 1
    messages_to_add = [ai_msg]

    # ── FIX #2: orphan tool_calls cleanup on MAX_TURNS cutoff ──────
    # Si el loop corta por MAX_TURNS y el AIMessage trae tool_calls sin
    # ejecutar, añadimos ToolMessage sintéticos para que Mistral no falle
    # con "Not the same number of function calls and responses" en el
    # siguiente turno de la misma sesión.
    if new_turn >= MAX_TURNS and getattr(ai_msg, "tool_calls", None):
        orphan_messages = [
            ToolMessage(
                content=(
                    "TIMEOUT_MAX_TURNS: Búsqueda finalizada por límite de "
                    "turnos. No esperes más resultados de esta tool."
                ),
                tool_call_id=(tc["id"] if isinstance(tc, dict) else tc.id),
            )
            for tc in (ai_msg.tool_calls or [])
        ]
        messages_to_add.extend(orphan_messages)

    return {
        "messages": messages_to_add,
        "turn_count": new_turn,
    }


# ── node: tools_node ───────────────────────────────────────────────────────


_tools_node_instance = ToolNode(list(TOOL_REGISTRY.values()))


def tools_node(state: AgentState) -> dict:
    """Ejecuta las tool_calls del último AIMessage vía ``ToolNode`` de LangGraph.

    Los ``ToolMessage`` resultantes se añaden automáticamente a
    ``state["messages"]`` vía el reducer ``add_messages``.
    """
    return _tools_node_instance.invoke(state)


# ── node: post_tools ───────────────────────────────────────────────────────


NO_ENCONTRE_HONEST = (
    "No encontré información que coincida con tu búsqueda en nuestro catálogo actual.\n\n"
    "🔍 Sugerencias para mejorar la búsqueda:\n"
    "• Usa el código SAP de 9 dígitos si lo conoces\n"
    "• Especifica la marca (Hikvision, HiLook, HIKMICRO, EZVIZ, Dahua, Outsource)\n"
    "• Indica el tipo de producto (cámara, NVR, switch, DVR, cable)\n"
    "• Reformula la consulta con palabras más específicas\n\n"
    "También puedes consultar con un ejecutivo de HELITEB."
)

TIMEOUT_HONEST = (
    "⏳ Tomé demasiado tiempo procesando esta consulta (límite de turnos alcanzado).\n\n"
    "Las herramientas recolectaron datos pero no alcancé a redactar la respuesta final. "
    "¿Reformulando con consultas más específicas? Ej: 'cámara WiFi EZVIZ con detección de personas'. "
    "También puedes consultar con un ejecutivo de HELITEB."
)


def post_tools(state: AgentState) -> AgentState:
    """Finaliza la respuesta: extrae del último AIMessage, aplica guardrails
    y guarda como AIMessage en state para el siguiente turno.
    """
    # ── Extract response from last FINAL AI response (sin tool_calls) ──
    # del turno actual (filtrado por _last_final_ai_response que se detiene
    # en el último HumanMessage para no descender a turnos anteriores).
    if not state.get("response"):
        last_ai = _last_final_ai_response(state["messages"])
        if last_ai:
            content = str(last_ai.content or "").strip()
            state["response"] = content if content else (
                TIMEOUT_HONEST if state.get("turn_count", 0) >= MAX_TURNS
                else NO_ENCONTRE_HONEST
            )
        else:
            # Loop terminó sin respuesta final AIMessage sin tool_calls.
            # Distinguir: ¿fue por MAX_TURNS (timeout) o raro/inesperado?
            state["response"] = (
                TIMEOUT_HONEST if state.get("turn_count", 0) >= MAX_TURNS
                else NO_ENCONTRE_HONEST
            )

    # ── Guardrails sobre el último ToolMessage (si existe) ─────────────
    # FIX #3: solo sobrescribir si el LLM no armó una respuesta válida
    # con productos (SAPs o marcas conocidas). Evita pisar la respuesta
    # del LLM cuando un ToolMessage intermedio dice "0 resultados" pero
    # el LLM ya redactó una respuesta con productos válidos.
    last_tool = _last_tool_message(state["messages"])
    if last_tool and _is_empty_or_error(last_tool.content):
        # Solo sobrescribir si el LLM no armó una respuesta válida con productos
        if not state.get("response") or not _has_product_markers(state["response"]):
            state["response"] = NO_ENCONTRE_HONEST
    elif last_tool and _is_low_quality(last_tool.content):
        # Advertencia solo si el LLM no incluyó ya su propia advertencia
        if "ADVERTENCIA" not in (state.get("response") or "").upper():
            state["response"] = (
                "⚠️ ADVERTENCIA: Búsqueda con pocos resultados precisos. "
                "SOLO menciono los productos de abajo. NO inventes.\n\n"
                f"{state['response']}"
            )

    # ── Normalize COP strings + log informal register (no modifica) ───
    state["response"] = _normalize_cop_strings(state["response"])
    _check_spanish_register(state["response"])

    # ── Set intent (refuerza el de scope_tools_by_intent) ──────────────
    scope = state.get("tools_scope", {}).get("scope", "other")
    state["intent"] = _SCOPE_TO_LEGACY_INTENT.get(scope, "other")
    # Si el scope es product_query y el mensaje es de precio, mantener "price"
    if scope == "product_query":
        last_human = _last_human_message(state["messages"])
        if last_human and _PRICE_RE.search(_msg_content(last_human)):
            state["intent"] = "price"

    # ── Save as AIMessage en state["messages"] (vía reducer) ───────────
    _save_assistant_message(state)

    return state


# ── conditional edge: route after agent_node ────────────────────────────────


def _route_after_agent(state: AgentState) -> str:
    """Decide el siguiente nodo después de ``agent_node``.

    - Si ``turn_count >= MAX_TURNS`` → post_tools (cortamos el loop)
    - Si el último AIMessage tiene ``tool_calls`` → tools_node
    - Si no → post_tools (respuesta final del LLM)
    """
    if state.get("turn_count", 0) >= MAX_TURNS:
        return "post_tools"
    last_ai = _last_ai_message(state["messages"])
    if last_ai and getattr(last_ai, "tool_calls", None):
        return "tools_node"
    return "post_tools"


# ── build_graph ─────────────────────────────────────────────────────────────


def build_graph():
    """Construye y compila el grafo ReAct.

    Topología:
        START → scope_tools_by_intent → agent_node
                                          ↓ (conditional)
                              tools_node ← tool_calls? → post_tools → END
                                  ↓
                              agent_node (loop, max MAX_TURNS veces)
    """
    workflow = StateGraph(AgentState)
    workflow.add_node("scope_tools_by_intent", scope_tools_by_intent)
    workflow.add_node("agent_node", agent_node)
    workflow.add_node("tools_node", tools_node)
    workflow.add_node("post_tools", post_tools)

    workflow.set_entry_point("scope_tools_by_intent")
    workflow.add_edge("scope_tools_by_intent", "agent_node")
    workflow.add_conditional_edges(
        "agent_node",
        _route_after_agent,
        {"tools_node": "tools_node", "post_tools": "post_tools"},
    )
    workflow.add_edge("tools_node", "agent_node")
    workflow.add_edge("post_tools", END)

    return workflow.compile(checkpointer=MemorySaver())


agent_graph = build_graph()


# ── Helpers (conservados del archivo original) ─────────────────────────────


def _msg_content(msg) -> str:
    """Extrae el contenido de un mensaje del historial (dict o LangChain object)."""
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(getattr(msg, "content", msg))


def _last_ai_message(messages) -> AIMessage | None:
    """Devuelve el último AIMessage del turno actual (tenga o no tool_calls).

    Se detiene al encontrar el último HumanMessage — solo considera mensajes
    del turno actual. Esto evita que el routing confunda AIMessages con
    tool_calls de turnos anteriores.

    USADA POR ROUTING: necesita detectar tool_calls para enrutar a tools_node.
    """
    for m in reversed(messages):
        if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") == "user"):
            break
        if isinstance(m, AIMessage):
            return m
    return None


def _last_final_ai_response(messages) -> AIMessage | None:
    """Devuelve el último AIMessage SIN tool_calls del turno actual (respuesta final).

    Se detiene al encontrar el último HumanMessage — por la misma razón que
    ``_last_ai_message``: solo.Messages del turno actual.

    USADA POR POST_TOOLS: necesita la respuesta final del LLM (sin tool_calls)
    para extraer el texto. Si el turno actual corta por MAX_TURNS sin respuesta
    final, devuelve None — el caller debe caer a NO_ENCONTRE_HONEST o
    TIMEOUT_HONEST.
    """
    for m in reversed(messages):
        if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") == "user"):
            break
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            return m
    return None


def _last_human_message(messages):
    """Devuelve el HumanMessage/dict-user más reciente, o None."""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m
        if isinstance(m, dict) and m.get("role") == "user":
            return m
    return None


def _last_tool_message(messages) -> ToolMessage | None:
    """Devuelve el ToolMessage más reciente, o None."""
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            return m
    return None


# ── COP formatting & response quality helpers ──────────────────────────────


_COP_PATTERN = re.compile(r'\$\s*(\d{1,3}(?:,\d{3})+)\s*(COP)?')
_INFORMAL_MARKERS = re.compile(
    r'\b(tú|tienes|estás|puedes|quieres)\b', re.IGNORECASE
)

_INTENT_TEMPLATES: dict[str, str] = {
    "specs": (
        "Presenta la ficha técnica así:\n"
        "*Marca Modelo*\n"
        "• Resolución: ...\n"
        "• Tecnología: ...\n"
        "(usa bullets '•' para todos los campos parametro_*)"
    ),
    "price": (
        "Presenta el precio así:\n"
        "*Marca Modelo*\n"
        "Precio MSRP: $ X.XXX.XXX COP"
    ),
    "stock": (
        "Presenta el stock así:\n"
        "*Marca Modelo* (SAP: X)\n"
        "  • Bodega (Ciudad): N unidades\n"
        "Total: N unidades\n"
        "Si el asesor preguntó por una bodega específica y NO aparece "
        "en la lista, di claramente que no hay stock en esa bodega y "
        "menciona en cuáles sí hay."
    ),
    "cross_sell": "cross_sell",
    "quotation": "quotation",
}

_SIMPLE_INTENTS = frozenset({"greeting"})


def _format_cop(n: float) -> str:
    """Format a number as Colombian pesos with dot thousands separator."""
    formatted = f"{int(round(n)):,}".replace(",", ".")
    return f"$ {formatted} COP"


def _normalize_cop_strings(text: str) -> str:
    """Replace comma thousands separators in COP strings with dots."""
    def _replace(m: re.Match) -> str:
        dots = m.group(1).replace(",", ".")
        suffix = " COP" if m.group(2) else ""
        return f"$ {dots}{suffix}"

    return _COP_PATTERN.sub(_replace, text or "")


def _truncate_response(response: str) -> str:
    """Truncation disabled — returns response as-is."""
    return response


def _check_spanish_register(response: str) -> None:
    """Warn if response uses informal second-person (tú) instead of usted."""
    if _INFORMAL_MARKERS.search(response):
        logger.warning(
            "Response contains informal second-person markers (tú form). "
            "SYSTEM_PROMPT requires usted form."
        )


def _save_assistant_message(state: AgentState) -> None:
    """Guarda la respuesta del agente como un AIMessage en ``state["messages"]``
    para que el reducer ``add_messages`` lo acumule en el checkpoint y esté
    disponible en el siguiente turno.
    """
    response = state.get("response", "")
    if response:
        state["messages"] = state["messages"] + [AIMessage(content=response)]


def _is_empty_or_error(tool_output: str) -> bool:
    """Detecta tool sin resultados o con error.

    Devuelve True (bypass LLM) solo si el output contiene marcadores de
    vacío/error Y NO contiene marcadores de éxito.
    """
    out = str(tool_output or "").lower()

    ok_markers = [
        "argumentos de venta",
        "nuestro precio",
        "cotización", "cotizacion",
        "instalación", "instalacion",
        "stock —",
        "ficha técnica", "ficha tecnica",
        "precio msrp",
        "cámaras bullet",
        "unidades disponible",
        "disponibilidad por bodega",
    ]
    if any(m in out for m in ok_markers):
        return False

    empty_markers = [
        "no encontré", "no encontre",
        "0 resultados", "0 coincidencias", "no hay datos",
        "error consultando", "error al consultar",
        "no encontre el producto", "no encontre productos",
        "❌ no encontré", "❌ error",
        "sin stock en ninguna bodega",
    ]
    return any(m in out for m in empty_markers)


def _is_low_quality(tool_output: str) -> bool:
    """Detecta resultados que probablemente son ruido, no matches reales."""
    tool_text = str(tool_output or "")
    sap_codes = re.findall(r'\b\d{9}\b', tool_text)
    if len(sap_codes) < 2:
        low = tool_text.lower()
        if "ficha técnica" in low or "ficha tecnica" in low:
            return False
        if "cotización" in low or "cotizacion" in low:
            return False
        if "instalación" in low or "instalacion" in low:
            return False
        if "stock" in low and ("unidades" in low or "disponible" in low or "sin stock" in low):
            return False
        return True
    return False


_MARCAS_CATALOGO_RE = re.compile(
    r'\b(hikvision|hilook|hikmicro|ezviz|dahua|outsource)\b',
    re.IGNORECASE,
)
_MODEL_PATTERN_RE = re.compile(
    r'\b(?:DS-|CS-|iDS-|DH-|NVR-|DVR-|DS-K|DS-2|THC-|TV-)[A-Z0-9]',
    re.IGNORECASE,
)


def _has_product_markers(text: str) -> bool:
    """True si el texto contiene SAPs de 9 dígitos, marcas conocidas, o modelos del catálogo."""
    if not text:
        return False
    if re.findall(r'\b\d{9}\b', text):
        return True
    if _MARCAS_CATALOGO_RE.search(text):
        return True
    if _MODEL_PATTERN_RE.search(text):
        return True
    return False


# ── SAP / model helpers ────────────────────────────────────────────────────


def extract_sap(text: str) -> str:
    """Extrae código SAP de 9 dígitos del texto del usuario. Devuelve "" si no hay."""
    match = re.search(r'\b(\d{9})\b', text)
    return match.group(1) if match else ""


_HIKVISION_PREFIXES = frozenset([
    "DS-2CD", "DS-2DE", "DS-2CE", "DS-2DF", "DS-2DP",
    "DS-3E", "DS-7", "DH-", "NVR-", "DVR-", "DS-K",
])
_MODEL_RE = re.compile(
    r'\b(?:DS|DH|NVR|DVR|DS-2CD|DS-2DE|DS-2CE|DS-2DP|DS-3E|DS-7|DS-K)'
    r'[A-Z0-9\-]{3,}(?:\([^)]*\))?\b',
    re.IGNORECASE,
)


# ── format helpers ─────────────────────────────────────────────────────────


def _format_search_options(search_result: str) -> str:
    """Convierte el resultado de ``buscar_producto`` en opciones elegibles."""
    lines = (search_result or "").strip().splitlines()
    header = lines[0] if lines else "Resultados"
    products = []
    for ln in lines[1:]:
        match = re.search(r'\(SAP:\s*(\d{9})\)', ln)
        if match:
            sap = match.group(1)
            rest = ln[:match.start()].strip(" ▸•- ")
            products.append((sap, rest))

    if not products:
        short = search_result[:300]
        return f"{short}\n\n¿Cuál necesitas? Indícame el código SAP o el modelo exacto."

    opts = []
    for i, (sap, desc) in enumerate(products, 1):
        opts.append(f"  {i}. {desc} — SAP: **{sap}**")
    return (
        f"{header}\n\n"
        + "\n".join(opts)
        + "\n\n¿Cuál necesitas? Responde con el número, el SAP o el modelo exacto."
    )


def _extract_modelo_base(modelo: str) -> str:
    """Extrae el modelo base quitando sufijos de lente/región entre paréntesis."""
    if not modelo:
        return ""
    return modelo.split("(", 1)[0].strip().upper()


def _format_variant_choice(variants: list, modelo_base: str, intent: str) -> str:
    """Formatea una lista de variantes del mismo modelo base para que el usuario elija."""
    if not variants:
        return ""

    lines = [
        f"Encontré **{len(variants)} variantes** del modelo "
        f"*{modelo_base}* en nuestro catálogo:\n"
    ]
    for v in variants:
        sap = v.get("codigo_sap", "")
        modelo = v.get("modelo", "")
        precio_data = v.get("heliteb_precios")
        if isinstance(precio_data, list) and precio_data:
            precio_data = precio_data[0]
        precio = precio_data.get("precio_msrp_cop") if isinstance(precio_data, dict) else None
        precio_str = _format_cop(precio) if precio else "precio no disponible"
        lines.append(f"• **{modelo}** — SAP: `{sap}` — {precio_str}")

    lines.append(
        f"\n¿Cuál necesitas? Responde con el **código SAP** o el **modelo completo**."
    )
    return "\n".join(lines)


def _try_handle_variants(
    search_result: str,
    user_query: str,
    intent: str,
) -> str | None:
    """Si el resultado de búsqueda contiene variantes del mismo modelo base,
    retorna un mensaje formateado. None si no hay variantes detectables.
    """
    text = str(search_result or "")
    saps = re.findall(r'\b\d{9}\b', text)
    if len(saps) < 2:
        return None

    base = _extract_modelo_base(user_query)
    if not base:
        return None

    try:
        result = search_variants_by_model_prefix(base)
        data = result.data if hasattr(result, 'data') else []
    except Exception:
        logger.warning("Failed to query variants for prefix: %s", base)
        return None

    if len(data) < 2:
        return None

    return _format_variant_choice(data, base, intent)


# ── client / email extractors ──────────────────────────────────────────────


_NUMBERS: dict[str, int] = {
    "uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}


def _extract_quantity(text: str) -> int | None:
    """Extrae cantidad solicitada: 'cinco productos', '5 cámaras', etc."""
    low = text.lower()
    for word, num in _NUMBERS.items():
        if re.search(rf'\b{word}\b', low):
            return num
    m = re.search(r'\b(\d+)\b', low)
    return int(m.group(1)) if m else None


_PRICE_RANGE_RE = re.compile(
    r'(?:precio\s+)?'
    r'(?:'
    r'(?:menor|menos|inferior|debajo)\s+(?:a|de)\s+(\d{2,3})\s*mil|'
    r'(?:mayor|m[aá]s|superior|arriba)\s+(?:a|de)\s+(\d{2,3})\s*mil|'
    r'(?:entre|de)\s+(\d{2,3})\s*(?:mil\s*)?(?:y|a|~)\s*(\d{2,3})\s*mil'
    r')',
    re.IGNORECASE,
)


def _extract_price_range(text: str) -> tuple[float | None, float | None] | None:
    """Extrae rango de precio: 'menor a 100 mil', 'mayor a 200 mil', etc."""
    m = _PRICE_RANGE_RE.search(text)
    if not m:
        return None
    groups = m.groups()
    if groups[0]:
        return (None, float(groups[0]) * 1000)
    if groups[1]:
        return (float(groups[1]) * 1000, None)
    if groups[2] and groups[3]:
        return (float(groups[2]) * 1000, float(groups[3]) * 1000)
    return None


def _extract_client_name(text: str) -> str | None:
    """Extrae el nombre del cliente de un mensaje de cotización."""
    m = re.search(
        r'(?:para|de)\s+([A-ZÁÉÍÓÚ][a-záéíóú]+(?:\s+[A-ZÁÉÍÓÚ][a-záéíóú]+)*)',
        text,
    )
    return m.group(1).strip() if m else None


def _extract_email(text: str) -> str | None:
    """Extrae una dirección de email del mensaje del asesor."""
    m = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    if m:
        email = m.group(0).strip().lower().rstrip('.')
        return email if '@' in email and '.' in email.split('@')[-1] else None
    return None


def _greeting_response() -> str:
    """Saludo personal de Helia, asistente comercial de HELITEB."""
    return (
        "¡Hola! Soy Helia, tu asistente comercial de HELITEB. 👋\n\n"
        "Estoy aquí para ayudarte a encontrar productos, revisar precios, "
        "consultar stock, comparar opciones y generar cotizaciones en PDF. "
        "Trabajo con el catálogo completo de Hikvision, EZVIZ y más.\n\n"
        "Solo dime qué necesitas y lo resolvemos. ¿En qué puedo ayudarte hoy?"
    )
