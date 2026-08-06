---
title: Telegram Auto Forwarder Bot
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# 🤖 Telegram Auto Forwarder Bot

Bot que reenvía automáticamente mensajes entre canales. Configurable desde Telegram con menú de botones.

## Configuración inicial

En **Settings → Repository secrets** de HF:

| Variable | Descripción |
|---|---|
| `API_ID` | De https://my.telegram.org |
| `API_HASH` | De https://my.telegram.org |
| `BOT_TOKEN` | De @BotFather |
| `SUDO_USERS` | (opcional) IDs de admins: `[123456789]` |
| `CONFIG_CHANNEL_ID` | (opcional) Canal privado para persistencia |

## Cómo usar

Envía `/start` al bot y aparecerá un menú con botones:

- 📋 **Ver reglas** — muestra las reglas activas
- ➕ **Añadir regla** — te indica cómo agregar una
- ❌ **Eliminar regla** — selecciona qué regla borrar
- 🗑 **Limpiar todo** — borra todas las reglas
- 💾 **Guardar/Cargar** — persistencia de configuración
- ❓ **Ayuda completa** — guía detallada

## Comandos

| Comando | Descripción |
|---|---|
| `/start` | Menú principal |
| `/add <origen> <destino1> [destino2...]` | Añadir regla |
| `/remove <origen> [destino]` | Eliminar regla |
| `/list` | Listar reglas |
| `/clear` | Limpiar todo |
| `/save` | Guardar config |
| `/load [msg_id]` | Cargar config |
| `/fwd <chat_id> <límite>` | Reenviar antiguos |

## Persistencia

HF Spaces pierde archivos al reiniciar. Para no perder la config:
1. Crea canal **privado**, añade bot como **admin**
2. Pon el ID en `CONFIG_CHANNEL_ID` (Secrets)
3. Usa `/save` y `/load`

## Evitar que duerma

cron-job.org cada 5 min a:
`https://siriocu-telegram-forwarder-es.hf.space`
