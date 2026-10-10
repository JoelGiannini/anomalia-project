# Spec 003: Pipeline de Alertas y Análisis con IA (AIOps)

## 1. Flujo de Alertas
1. **Evaluación:** `vmalert` evalúa las reglas de métricas del tenant y dispara la alerta hacia `Alertmanager`.
2. **Webhook (DESHABILITADO):** el flujo AM → Backend está **apagado por decisión operativa**: el receiver global de Alertmanager es `console` (sin integraciones: ni `email_configs` ni `webhook_configs`), por lo que las alertas solo se consultan en la consola de Alertmanager. El SMTP/email se retiró del template `alertmanager.yml.j2` y sus vars (`mail`, `smtp_server_ip`, `smtp_server_port`) del inventario. **Pendiente de reactivar** con los dos fixes ya diagnosticados: (a) el endpoint `POST /api/v1/webhook/alertmanager` exige JWT admin (`verify_admin_token`) y AM no envía Authorization → `401`; (b) `FORCE_HTTPS=true` redirige con `301` el Host de AM (`192.168.1.27:8000`) y AM no sigue TLS autofirmado → hace falta exención de path en `enforce_https_redirect` (`backend/app/main.py`) y un token compartido AM↔backend (`http_config.bearer_token` en AM + env en el compose del backend). Hasta entonces, los pasos 3 y 4 no se ejecutan y `alert_history` queda vacío (no hay lector de esa tabla).
3. **Análisis IA:** El backend procesa la alerta, extrae el contexto y consulta al proveedor de IA configurado para obtener un diagnóstico de causa raíz y posibles soluciones. *(En pausa mientras el paso 2 esté deshabilitado.)*
4. **Distribución:** La alerta enriquecida se almacena y se transmite en tiempo real hacia la interfaz Web y la aplicación móvil Android para notificar al usuario. *(En pausa: además del paso 2, falta el feed de `alert_history` en la UI y el despacho push móvil.)*

## 2. Catálogo y Selección de Proveedores IA

El análisis de alertas usa un proveedor de IA único, seleccionable desde el panel de
control (pestaña «Proveedor IA») y persistido en la tabla `ai_settings` de
PostgreSQL. La selección es global al sistema (no por tenant).

### 2.1 Catálogo

| ID | Proveedor | Grupo | Requiere |
|---|---|---|---|
| `space-bunny-free` | Space Bunny Free | Free (OpenCode Zen) | API Key Zen |
| `anomalia_ollama` | anomalia_ollama (Local) | Local | — |
| `gemini` | Gemini (Google) | API Key | API Key Gemini |

- El proveedor Free se sirve desde el gateway **OpenCode Zen**
  (`https://opencode.ai/zen/v1`, API OpenAI-compatible, `/chat/completions`).
  Autenticación: `Authorization: Bearer <OPENCODE_API_KEY>`.
- `anomalia_ollama` es el contenedor Ollama local del stack
  (`OLLAMA_HOST` / `OLLAMA_MODEL` por env). **Sin límite de tokens de
  respuesta**: no se envía `num_predict` en las opciones de generación.
  El modelo por defecto es `llama3.2:1b` (var `ollama_model` en
  `roles/backend/defaults/main.yml`); el role `backend` lo descarga con
  `ollama pull` tras levantar el stack si aún no está en el volumen.
- `gemini` usa la API de Google
  (`https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent`)
  con la API Key ingresada en el panel. El modelo es seleccionable; por defecto
  `gemini-3.5-flash-lite`. La lista de modelos se obtiene dinámicamente de la
  API de Google cuando hay key configurada (fallback a lista estática).

### 2.2 Persistencia

Tabla `ai_settings` (fila única, sembrada con `anomalia_ollama`):

| Columna | Default | Uso |
|---|---|---|
| `selected_provider` | `anomalia_ollama` | Proveedor activo |
| `zen_api_key` | `''` | API Key Zen (modelos Free) |
| `gemini_api_key` | `''` | API Key Gemini |
| `gemini_model` | `gemini-3.5-flash-lite` | Modelo Gemini activo |
| `updated_at` | `CURRENT_TIMESTAMP` | Última modificación |

Las keys viven **únicamente en la BD** (volumen de Postgres). Nunca se
devuelven por la API: `GET /api/v1/ai/config` solo expone los flags
`has_zen_key` / `has_gemini_key`. Ninguna key se escribe en archivos del
repositorio (constitución §4).

### 2.3 API

Router `/api/v1/ai` (JWT admin obligatorio vía `verify_admin_token`):

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/ai/providers` | Catálogo completo con flag `configured` por proveedor |
| GET | `/api/v1/ai/config` | Selección actual + flags de keys + modelo Gemini |
| PUT | `/api/v1/ai/config` | Guarda selección y keys. Semántica de keys: campo ausente = sin cambios, `""` = borrar |
| POST | `/api/v1/ai/test` | Prueba el proveedor (prompt mínimo); devuelve `{ok, provider, response}` o `{ok: false, error}` |
| GET | `/api/v1/ai/gemini-models` | Modelos con soporte `generateContent` (lista dinámica con key, fallback estático) |

### 2.4 UI

Pestaña «Proveedor IA» del panel de control (`index.html#admin-view-ai`):
selector con `<optgroup>` Free / Local / API Key, campos de key condicionales
(visibles según el grupo del proveedor elegido), selector de modelo Gemini,
indicador de configuración («API Key configurada» / «Sin API Key») y botón
«Probar conexión» que invoca `POST /api/v1/ai/test` y muestra la respuesta.

### 2.5 Restricción conocida (OpenCode Zen)

Los modelos Free de Zen rechazan llamadas sin API Key válida
(`403 FreeTierError: "OpenCode's free tier can only be used from within
OpenCode"`). Sin la key Zen ingresada en el panel, el proveedor Free
aparece como «sin configurar» y `POST /api/v1/ai/test` devuelve el error del
gateway. La key se obtiene en https://opencode.ai/auth.

**Verificado 2026-10-02:** con una API Key Zen válida, el gateway solo
permite `space-bunny-free` desde fuera de la app. Los demás modelos Free
(`longcat-2.5-preview-free`, `nemotron-3-ultra-free`,
`muse-spark-1.3-contributor-free`, `ling-3.0-flash-fin-free`,
`nemotron-3.5-lightning-free`, `big-pickle`, `mimo-v2.6-flash-free`,
`mimo-v2.5-free`, `ling-3.1-flash-free`) devuelven `403 FreeTierError`
también. No es la key: es una restricción server-side del gateway. Por eso
el catálogo Free incluye únicamente Space Bunny.

### 2.6 Fallback de proveedor

Si el `selected_provider` guardado en BD ya no existe en el catálogo
(p. ej. un modelo free retirado), `get_provider()` y `GET /api/v1/ai/config`
exponen `anomalia_ollama` (el proveedor por defecto) en lugar de un id
inválido. No requiere migración de datos.
