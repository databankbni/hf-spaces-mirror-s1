# Project Context: inventario-mp-app

## Objetivo

App para gestionar inventario nacional de materia prima almacenada en tanques, priorizar movimientos hacia refinería y apoyar decisiones con IA.

La refinería principal es:

- NOMBRE: DANEC SANGOLQUI

## Fuente inicial de datos

La app lee el inventario de la tabla `inventario_mp_app_inventory` en Supabase (server-side, vía `/api/inventory`). El origen de negocio sigue siendo el consolidado `ANEXADO`, pero la carga manual de archivos se retiró de la app: los datos entran a Supabase por SQL o por un ETL externo.

Campos esperados:

- FECHA
- TIPO
- NOMBRE
- PRODUCTO
- TANQUE
- CAPACIDAD
- INVENTARIO
- DISPONIBLE
- ACIDEZ
- OC
- ORDEN RECIBIDA EN BODEGA
- FECHA ORDEN
- DIAS RETRAZO
- PEDIDO
- RETIRADO
- PENDIENTE RETIRO
- OBSERVACIÓN
- TRANSITO
- IMPORTACIONES

## Reglas de negocio conocidas

- Todas las cantidades están en toneladas.
- DISPONIBLE significa inventario neto después de merma.
- TIPO es una clasificación empresarial asociada al NOMBRE.
- NOMBRE es la denominación de la ubicación; cada nombre corresponde a una ciudad/ubicación.
- PRODUCTO es la materia prima.
- TANQUE identifica el tanque de almacenamiento.
- CAPACIDAD es finita por tanque.
- ACIDEZ es variable de decisión: mayor acidez encarece procesamiento.
- TRANSITO e IMPORTACIONES son cantidades comprometidas futuras en toneladas.
- PEDIDO, RETIRADO y PENDIENTE RETIRO se usan para evaluar demanda/movimientos.
- La app debe priorizar riesgos, continuidad de flujo a refinería, movimientos recomendados, rutas y costo por km.
- La flota disponible se cargará después desde otro archivo.
- Se planean notificaciones mediante bot de Telegram.
- Futuro: conexión a SingleStore vía ODBC o una capa server-side equivalente.

## Arquitectura actual

- Framework: Next.js + TypeScript.
- Deploy actual: Hugging Face Spaces con Docker.
- Repo GitHub: https://github.com/dmyandun/inventario-mp-app
- Space HF: https://huggingface.co/spaces/dyandun/inventario-mp-app

Archivos principales:

- `src/app/page.tsx`: interfaz principal y vistas.
- `src/app/api/inventory/route.ts`: lectura de los snapshots de inventario en Supabase.
- `src/lib/optimizer.ts`: motor heurístico de recomendaciones.
- `src/lib/sample-data.ts`: datos de ejemplo y rutas iniciales.
- `src/app/api/ai/route.ts`: inferencia con Hugging Face Router.
- `src/app/api/telegram/route.ts`: notificaciones por Telegram.
- `Dockerfile` / `Dockerfile.hf`: despliegue en HF Spaces.
- `.github/workflows/sync-to-hf-space-v2.yml`: sincroniza GitHub hacia HF Space.

## Variables de entorno

En Hugging Face Spaces configurar como secrets/variables:

- HF_TOKEN
- HF_MODEL
- HF_FALLBACK_MODELS
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Notas:

- `HF_TOKEN` debe permitir llamadas a Inference Providers.
- `HF_MODEL` puede ser `openai/gpt-oss-20b:fastest`.
- `HF_FALLBACK_MODELS` acepta modelos separados por coma.

## IA

La IA usa Hugging Face Router:

- Endpoint: `https://router.huggingface.co/v1/chat/completions`

Comportamiento esperado:

- No mostrar el modelo usado.
- No mostrar razonamiento interno.
- No mostrar bloques `<think>`.
- No usar Markdown con asteriscos.
- Responder con bullets accionables, máximo 5.
- Incluir prioridad, ubicación, toneladas sugeridas, motivo y riesgo.
- Cerrar con una acción inmediata.

## UI actual

Vistas activas:

- Inventario
- Refinería
- Rutas
- IA

Comportamiento actual:

- El botón superior `Analizar` abre la vista IA.
- El textbox de IA inicia vacío.
- Los prompts rápidos solo llenan el textbox.
- La consulta solo se ejecuta al presionar `Consultar con IA`.
- El área de respuesta inicia vacía.
- Durante consulta muestra estado de análisis.
- La respuesta IA se limpia para quitar Markdown básico y razonamiento interno.

## Próximos pasos probables

- Cargar datos reales desde Excel en la app.
- Agregar archivo/fuente de flota disponible.
- Reemplazar rutas de ejemplo por matriz real de `$ / km`.
- Mejorar modelo de optimización considerando:
  - capacidad de tanque,
  - inventario neto,
  - acidez,
  - demanda de refinería,
  - tránsito/importaciones,
  - capacidad de flota,
  - costo logístico.
- Activar Telegram con mensajes operativos.
- Preparar integración futura con SingleStore.
