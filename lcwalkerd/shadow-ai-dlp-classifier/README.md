---
title: Shadow AI DLP Classifier
emoji: 🛡️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Shadow AI — Servicio de NER (Capa 1b)

Servicio de reconocimiento de entidades (NER) en español para el pipeline de
Shadow AI Monitor. El backend corre todo el pipeline de reglas localmente; lo
único que delega acá es el NER, porque el modelo (Presidio + spaCy
`es_core_news_lg`) no cabe en las funciones serverless de Vercel.

Detecta: `PERSON`, `LOCATION`, `IP_ADDRESS`, `NRP`
(nacionalidad/religión/afiliación) y `ORGANIZATION` (empresas).

- `GET  /health` → estado
- `POST /ner` con `{"texto": "..."}` → `{entidades: [...], tags: [...]}`

Modo observación: solo detecta, no redacta.
