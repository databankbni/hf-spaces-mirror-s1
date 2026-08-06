"""Servicio de NER (Capa 1b) para Hugging Face Spaces.

El backend Node corre TODO el pipeline de reglas localmente (rápido, sin red).
Lo único que no puede correr es el NER: Presidio + spaCy es_core_news_lg (~568
MB) no cabe en las funciones serverless de Vercel (límite 250 MB). Así que ese
pedazo vive acá y el backend lo consulta best-effort, fusionando estos tags
con los suyos.

Espeja capas/ner.py (misma config, mismos tipos). Modo observación: solo
detecta, no redacta. Requiere modelo de spaCy (lo baja el Dockerfile).

  GET  /health -> {ok, backend}
  POST /ner    {"texto": "..."} -> {entidades:[{tipo,valor,inicio,fin,score}],
                                     tags:[tipos únicos ordenados]}
"""
from fastapi import FastAPI, Request
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

# Solo estos tipos (filtro obligatorio: sin él Presidio también devolvería
# EMAIL/PHONE/CREDIT_CARD/IBAN, que el backend ya cubre con regex).
TIPOS_NER = ["PERSON", "LOCATION", "IP_ADDRESS", "NRP", "ORGANIZATION"]

# Presidio viene para inglés por defecto; mapeamos "es" -> es_core_news_lg.
# Se configura UNA vez (cargar el modelo es lo caro; ~50 s en el arranque).
_cfg = {"nlp_engine_name": "spacy",
        "models": [{"lang_code": "es", "model_name": "es_core_news_lg"}]}
_nlp = NlpEngineProvider(nlp_configuration=_cfg).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp, supported_languages=["es"])

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "servicio": "ner"}


@app.get("/health")
def health():
    return {"ok": True, "backend": "ner"}


@app.post("/ner")
async def ner(request: Request):
    body = await request.json()
    texto = body.get("texto") or body.get("text") or ""
    resultados = _analyzer.analyze(text=texto, language="es", entities=TIPOS_NER)
    entidades = [
        {"tipo": r.entity_type, "valor": texto[r.start:r.end],
         "inicio": r.start, "fin": r.end, "score": r.score}
        for r in resultados
    ]
    return {"entidades": entidades,
            "tags": sorted({e["tipo"] for e in entidades})}
