"""Auditoria end-to-end del agente HELITEB.

Ejecuta conversaciones multi-turno que simulan un asesor real
evaluando los 4 requerimientos funcionales obligatorios + memoria.

Uso:
    cd Agente-Heliteb/agent
    python test_audit.py
"""
import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from graph import agent_graph, resolve_references

# ── Helpers ──────────────────────────────────────────────────────────────────

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

results: list[dict] = []


def run_turn(thread_id: str, message: str, turn: int) -> dict:
    """Ejecuta un turno y retorna el estado resultante."""
    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "messages": [{"role": "user", "content": message}],
        "intent": "",
        "tool_result": "",
        "response": "",
        "email_address": "",
    }
    return agent_graph.invoke(state, config)


def check(case_id: str, description: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    results.append({"id": case_id, "desc": description, "status": status, "detail": detail})
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}[status]
    print(f"  {tag} {case_id}: {description}")
    if detail:
        print(f"         {detail}")


def check_warn(case_id: str, description: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else WARN
    results.append({"id": case_id, "desc": description, "status": status, "detail": detail})
    tag = {"PASS": "[PASS]", "WARN": "[WARN]"}[status]
    print(f"  {tag} {case_id}: {description}")
    if detail:
        print(f"         {detail}")


def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


# ── RQ1: Especificaciones Tecnicas ───────────────────────────────────────────


def test_rq1():
    section("RQ1 — Especificaciones Tecnicas")

    # 1.1 — SAP explicito
    r = run_turn("audit-rq1-1", "dame las especificaciones de 311315990", 1)
    resp = r.get("response", "").lower()
    check("1.1", "SAP explicito devuelve ficha tecnica",
          any(k in resp for k in ["hikvision", "ds-2cd", "ficha", "resolucion", "marca"]),
          f"intent={r.get('intent')}")

    # 1.2 — Busqueda por modelo
    r = run_turn("audit-rq1-2", "que sabes del DS-2CD1023G0E-I?", 1)
    resp = r.get("response", "").lower()
    check("1.2", "Busqueda por modelo encuentra el producto",
          any(k in resp for k in ["hikvision", "ds-2cd", "ficha", "resolucion", "marca"]),
          f"intent={r.get('intent')}")

    # 1.3 — Busqueda semantica por descripcion
    r = run_turn("audit-rq1-3", "especificaciones de la camara bullet Hikvision", 1)
    resp = r.get("response", "").lower()
    check("1.3", "Busqueda semantica por descripcion",
          any(k in resp for k in ["hikvision", "camara", "bullet", "sap", "modelo"]),
          f"intent={r.get('intent')}")

    # 1.4 — Cross sell
    r = run_turn("audit-rq1-4", "que accesorios hay para 311315990?", 1)
    resp = r.get("response", "").lower()
    check_warn("1.4", "Cross sell sugiere complementos",
               any(k in resp for k in ["complement", "accesori", "nvr", "switch", "cable"]),
               f"intent={r.get('intent')}")

    # 1.5 — Filtro por linea
    r = run_turn("audit-rq1-5", "mostrame camaras de la linea Raw Material", 1)
    resp = r.get("response", "").lower()
    check("1.5", "Busqueda filtrada por linea 'Raw Material'",
          any(k in resp for k in ["raw", "producto", "sap", "modelo", "$"]),
          f"intent={r.get('intent')}")


# ── RQ2: Consulta de Precios ─────────────────────────────────────────────────


def test_rq2():
    section("RQ2 — Consulta de Precios")

    # 2.1 — Precio por SAP
    r = run_turn("audit-rq2-1", "precio de 311315990", 1)
    resp = r.get("response", "")
    has_cop = "$" in resp and "COP" in resp
    has_dot_sep = bool(re.search(r'\$\s*\d{1,3}(\.\d{3})+\s*COP', resp))
    check("2.1", "Precio MSRP en formato COP con punto separador",
          has_cop and has_dot_sep,
          f"intent={r.get('intent')}")

    # 2.2 — Precio por descripcion semantica
    r = run_turn("audit-rq2-2", "cuanto cuesta el NVR de 16 canales?", 1)
    resp = r.get("response", "")
    check_warn("2.2", "Precio por descripcion semantica (NVR 16ch)",
               "$" in resp and "COP" in resp,
               f"intent={r.get('intent')}")

    # 2.3 — Filtro: accesorios baratos (sort price_asc)
    r = run_turn("audit-rq2-3", "accesorios baratos", 1)
    resp = r.get("response", "").lower()
    # Los filtros de _extract_search_filters van a search_filters (local en execute_tool),
    # no a resolved_context. Verificamos que la respuesta contenga productos o precios.
    check("2.3", "Busqueda 'accesorios baratos' devuelve productos",
          any(k in resp for k in ["$", "cop", "sap", "accesori", "producto", "modelo"]),
          f"intent={r.get('intent')}")

    # 2.4 — Precio con memoria ("este producto" despues de 311315990)
    tid = "audit-rq2-4"
    run_turn(tid, "especificaciones de 311315990", 1)
    r = run_turn(tid, "dame el precio de este producto", 2)
    resp = r.get("response", "")
    resolved = r.get("resolved_context", {})
    resolved_saps = resolved.get("resolved_saps", [])
    check("2.4", "Precio con memoria: 'este producto' resolve al SAP anterior",
          "311315990" in resolved_saps and "$" in resp and "COP" in resp,
          f"resolved_saps={resolved_saps}")


# ── RQ3: Disponibilidad (Stock) ──────────────────────────────────────────────


def test_rq3():
    section("RQ3 — Disponibilidad (Stock)")

    # 3.1 — Stock por SAP
    r = run_turn("audit-rq3-1", "hay stock de 311315990?", 1)
    resp = r.get("response", "").lower()
    has_bodega = any(b in resp for b in ["obrero", "centro", "monteria", "bogota", "bodega", "unidades"])
    check_warn("3.1", "Stock por SAP lista bodegas",
               has_bodega or "stock" in resp or "disponib" in resp,
               f"intent={r.get('intent')}")

    # 3.2 — Stock en bodega especifica
    r = run_turn("audit-rq3-2", "disponibilidad de 311315990 en Obrero", 1)
    resp = r.get("response", "").lower()
    check_warn("3.2", "Stock en bodega Obrero",
               "obrero" in resp or "stock" in resp or "disponib" in resp,
               f"intent={r.get('intent')}")

    # 3.3 — Stock con memoria ("hay stock?" despues de discutir un producto)
    tid = "audit-rq3-3"
    run_turn(tid, "especificaciones de 311315990", 1)
    r = run_turn(tid, "y hay stock?", 2)
    resp = r.get("response", "").lower()
    recent_saps = r.get("recent_saps", [])
    check("3.3", "Stock con memoria: 'hay stock?' usa el SAP anterior",
          "311315990" in recent_saps,
          f"recent_saps={recent_saps}")


# ── RQ4: Comparativa Comercial ───────────────────────────────────────────────


def test_rq4():
    section("RQ4 — Comparativa Comercial")

    # 4.1 — Comparar dos SAPs explicitos
    r = run_turn("audit-rq4-1", "comparar 311315990 y 311315672", 1)
    resp = r.get("response", "").lower()
    check("4.1", "Comparar dos SAPs explicitos",
          any(k in resp for k in ["producto 1", "comparacion", "diferencia", "vs", "ambas", "modelo"]),
          f"intent={r.get('intent')}")

    # 4.2 — "cual es la diferencia entre estos dos?" despues de 2 productos
    tid = "audit-rq4-2"
    run_turn(tid, "especificaciones de 311315990", 1)
    run_turn(tid, "especificaciones de 311315672", 2)
    r = run_turn(tid, "cual es la diferencia entre estos dos?", 3)
    resolved = r.get("resolved_context", {})
    resolved_saps = resolved.get("resolved_saps", [])
    check("4.2", "Comparativa con memoria: 'estos dos' resuelve a 2 SAPs",
          len(resolved_saps) >= 2,
          f"resolved_saps={resolved_saps}")

    # 4.3 — "compara estas dos" despues de 2 productos
    tid = "audit-rq4-3"
    run_turn(tid, "especificaciones de 311315990", 1)
    run_turn(tid, "especificaciones de 311315672", 2)
    r = run_turn(tid, "compara estas dos", 3)
    resolved = r.get("resolved_context", {})
    resolved_saps = resolved.get("resolved_saps", [])
    check("4.3", "'compara estas dos' resuelve a los 2 ultimos SAPs",
          "311315990" in resolved_saps and "311315672" in resolved_saps,
          f"resolved_saps={resolved_saps}")


# ── RQ5: Memoria Conversacional ──────────────────────────────────────────────


def test_rq5():
    section("RQ5 — Memoria Conversacional")

    # 5.1 — "de la misma linea" despues de un producto
    tid = "audit-rq5-1"
    run_turn(tid, "especificaciones de 311315990", 1)
    r = run_turn(tid, "de la misma linea", 2)
    resolved = r.get("resolved_context", {})
    filters = resolved.get("resolved_filters", {})
    recent_linea = r.get("recent_linea", "")
    check("5.1", "'de la misma linea' resuelve a recent_linea",
          "linea" in filters and filters["linea"] == recent_linea,
          f"resolved_filters={filters}, recent_linea={recent_linea}")

    # 5.2 — "compara estas dos" despues de 2 productos
    tid = "audit-rq5-2"
    run_turn(tid, "especificaciones de 311315990", 1)
    run_turn(tid, "especificaciones de 311315672", 2)
    r = run_turn(tid, "compara estas dos", 3)
    resolved = r.get("resolved_context", {})
    resolved_saps = resolved.get("resolved_saps", [])
    check("5.2", "'compara estas dos' con 2 SAPs en memoria",
          len(resolved_saps) == 2,
          f"resolved_saps={resolved_saps}")

    # 5.3 — "este producto" despues de 1 producto
    tid = "audit-rq5-3"
    run_turn(tid, "especificaciones de 311315990", 1)
    r = run_turn(tid, "dame el precio de este producto", 2)
    resolved = r.get("resolved_context", {})
    resolved_saps = resolved.get("resolved_saps", [])
    check("5.3", "'este producto' resuelve al ultimo SAP",
          "311315990" in resolved_saps,
          f"resolved_saps={resolved_saps}")

    # 5.4 — "y hay stock?" hereda intent y usa SAP anterior
    tid = "audit-rq5-4"
    run_turn(tid, "especificaciones de 311315990", 1)
    r = run_turn(tid, "y hay stock?", 2)
    recent_saps = r.get("recent_saps", [])
    intent = r.get("intent", "")
    check("5.4", "'y hay stock?' hereda intent y usa SAP anterior",
          "311315990" in recent_saps and intent in ("stock", "specs"),
          f"intent={intent}, recent_saps={recent_saps}")


# ── RQ6: Cotizacion con Memoria ──────────────────────────────────────────────


def test_rq6():
    section("RQ6 — Cotizacion con Memoria")

    # 6.1 — "envia cotizacion de estas dos al correo X" despues de 2 productos
    tid = "audit-rq6-1"
    run_turn(tid, "especificaciones de 311315990", 1)
    run_turn(tid, "especificaciones de 311315672", 2)
    r = run_turn(tid, "envia cotizacion de estas dos al correo test@test.com", 3)
    resolved = r.get("resolved_context", {})
    resolved_saps = resolved.get("resolved_saps", [])
    email = r.get("email_address", "")
    quote_saps = r.get("quotation_saps", "")
    check("6.1", "Cotizacion con memoria: resolved_saps + email",
          "311315990" in resolved_saps and "311315672" in resolved_saps
          and email == "test@test.com",
          f"resolved_saps={resolved_saps}, email={email}, quote_saps={quote_saps}")


# ── Casos Edge ───────────────────────────────────────────────────────────────


def test_edge():
    section("Casos Edge")

    # E.1 — Saludo
    r = run_turn("audit-edge-1", "hola", 1)
    resp = r.get("response", "").lower()
    check("E.1", "Saludo no busca productos",
          any(k in resp for k in ["hola", "helia", "ayudarte", "bienvenido"]),
          f"intent={r.get('intent')}")

    # E.2 — Mensaje sin sentido
    r = run_turn("audit-edge-2", "xyzzy blorgh", 1)
    resp = r.get("response", "")
    check("E.2", "Mensaje sin sentido no crashea",
          len(resp) > 0,
          f"intent={r.get('intent')}")

    # E.3 — Cotizacion sin SAP ni descripcion
    r = run_turn("audit-edge-3", "cotizacion", 1)
    resp = r.get("response", "").lower()
    check("E.3", "Cotizacion sin datos pide mas info",
          any(k in resp for k in ["sap", "nombre", "necesito", "producto", "cliente"]),
          f"intent={r.get('intent')}")


# ── Resumen ──────────────────────────────────────────────────────────────────


def print_summary():
    section("RESUMEN DE AUDITORIA")
    total = len(results)
    passed = sum(1 for r in results if r["status"] == PASS)
    warned = sum(1 for r in results if r["status"] == WARN)
    failed = sum(1 for r in results if r["status"] == FAIL)

    print(f"  Total: {total}  |  PASS: {passed}  |  WARN: {warned}  |  FAIL: {failed}")
    print(f"  Tasa de exito: {passed}/{total} = {passed/total*100:.0f}%")

    if failed:
        print(f"\n  FALLOS:")
        for r in results:
            if r["status"] == FAIL:
                print(f"    [{r['id']}] {r['desc']}")
                if r["detail"]:
                    print(f"         {r['detail']}")

    if warned:
        print(f"\n  ADVERTENCIAS (posibles mejoras):")
        for r in results:
            if r["status"] == WARN:
                print(f"    [{r['id']}] {r['desc']}")
                if r["detail"]:
                    print(f"         {r['detail']}")

    print(f"\n{'='*70}")
    print(f"  Auditoria completada.")
    print(f"{'='*70}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("=" * 70)
    print("  AUDITORIA DEL AGENTE HELITEB")
    print("  Evaluando requerimientos funcionales + memoria conversacional")
    print("=" * 70)

    start = time.time()

    test_rq1()
    test_rq2()
    test_rq3()
    test_rq4()
    test_rq5()
    test_rq6()
    test_edge()

    print_summary()

    elapsed = time.time() - start
    print(f"  Tiempo total: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
