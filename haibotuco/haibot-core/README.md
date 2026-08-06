---
title: Haibot Core
emoji: 💬
colorFrom: purple
colorTo: blue
sdk: docker
pinned: false
app_port: 7860
base_path: /status
startup_duration_timeout: 1h
---

# Haibot Chat

Space Docker unico para Haibot. Ejecuta Rasa 3.6.21 y el action server `rasa-sdk` dentro del mismo contenedor.

El modelo se entrena durante el build Docker. El contenedor expone `/status`, `/health` y `/webhooks/rest/webhook` en el puerto 7860.
