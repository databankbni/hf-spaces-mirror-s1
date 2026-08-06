# Auditoria del Agente HELITEB — Casos de Uso

> Pruebas end-to-end que evaluan las capacidades del agente contra los
> 4 requerimientos funcionales obligatorios + memoria conversacional.
> Cada caso simula un asesor que nunca ha usado el agente.

## Como usar este archivo

1. Ejecutar: `python test_audit.py` (desde `Agente-Heliteb/agent/`)
2. Cada caso imprime: Pregunta, Respuesta, Veredicto (PASS/WARN/FAIL)
3. Al final se imprime un resumen con metricas

---

## RQ1 — Especificaciones Tecnicas

**Objetivo:** Entregar detalles claros sobre cualquier producto basandose
en las descripciones del catalogo (Hikvision, EZVIZ, etc.).

| # | Pregunta del asesor | Lo que debe pasar |
|---|---|---|
| 1.1 | "dame las especificaciones de 311315990" | Ficha tecnica con marca, modelo, resolucion, tecnologia, parametros |
| 1.2 | "que sabes del DS-2CD1023G0E-I?" | Busca por modelo, encuentra el SAP, entrega ficha |
| 1.3 | "especificaciones de la camara bullet Hikvision" | Busqueda semantica por descripcion, muestra opciones o ficha |
| 1.4 | "que accesorios hay para 311315990?" | Sugerencia de complementos (cross_sell) |
| 1.5 | "mostrame camaras de la linea Raw Material" | Filtrado por linea, lista productos de esa linea |

## RQ2 — Consulta de Precios

**Objetivo:** Informar el precio MSRP en COP con separador de miles por punto.

| # | Pregunta del asesor | Lo que debe pasar |
|---|---|---|
| 2.1 | "precio de 311315990" | Precio MSRP en formato `$ X.XXX.XXX COP` |
| 2.2 | "cuanto cuesta el NVR de 16 canales?" | Busca semánticamente, muestra precio del producto encontrado |
| 2.3 | "accesorios baratos" | Filtra por categoria=Accesories + sort=price_asc |
| 2.4 | "precio de este producto" (despues de RQ1.1) | Usa memoria: resuelve al ultimo SAP mencionado |

## RQ3 — Disponibilidad (Stock)

**Objetivo:** Responder si hay mercancia y en que bodegas (Obrero, Centro,
Monteria, Bogota).

| # | Pregunta del asesor | Lo que debe pasar |
|---|---|---|
| 3.1 | "hay stock de 311315990?" | Lista bodegas con cantidades |
| 3.2 | "disponibilidad de 311315990 en Obrero" | Resalta la bodega Obrero primero |
| 3.3 | "hay stock?" (despues de RQ1.1) | Usa memoria: busca stock del ultimo producto discutido |

## RQ4 — Comparativa Comercial

**Objetivo:** Comparar productos y precios para dar argumentos de venta.

| # | Pregunta del asesor | Lo que debe pasar |
|---|---|---|
| 4.1 | "comparar 311315990 y 311315672" | Compara dos productos por SAP explicito |
| 4.2 | "cual es la diferencia entre estos dos?" (despues de 2 productos) | Usa memoria: resuelve a los 2 ultimos SAPs |
| 4.3 | "compara estas dos" (despues de buscar 2 productos) | Usa memoria: resolved_saps = recent_saps[-2:] |

## RQ5 — Memoria Conversacional (NO en requerimientos originales)

**Objetivo:** El agente debe recordar el contexto de la conversacion.

| # | Secuencia | Lo que debe pasar |
|---|---|---|
| 5.1 | "311315990" → "de la misma linea" | resolved_filters = {linea: recent_linea} |
| 5.2 | "311315990" → "311315672" → "compara estas dos" | resolved_saps = [311315990, 311315672] |
| 5.3 | "311315990" → "dame el precio de este producto" | resolved_saps = [311315990] |
| 5.4 | "311315990" → "y hay stock?" | Hereda intent, busca stock del ultimo SAP |

## RQ6 — Cotizacion con Memoria

| # | Pregunta del asesor | Lo que debe pasar |
|---|---|---|
| 6.1 | "envia cotizacion de estas dos al correo test@test.com" (despues de 2 productos) | Usa resolved_saps para cotizar los productos correctos |

## Casos Edge

| # | Pregunta | Lo que debe pasar |
|---|---|---|
| E.1 | "hola" | Saludo, no busca productos |
| E.2 | "xyzzy blorgh" | No crash, respuesta de saludo o "other" |
| E.3 | "cotizacion" (sin SAP ni descripcion) | Pide mas info, no genera PDF vacio |
