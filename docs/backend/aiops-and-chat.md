# Pipeline AIOps y Asistente de IA

El pipeline de Inteligencia Artificial de Anomalia procesa, enriquece y diagnostica alertas de forma asíncrona, proporcionando además un asistente interactivo con restricciones estrictas de contexto.

---

## 1. Proveedores de IA Soportados

La configuración del proveedor se gestiona de forma centralizada en la tabla `ai_settings` de PostgreSQL (accesible desde el panel de administración):

| Proveedor | Identificador | Descripción y Consideraciones |
| :--- | :--- | :--- |
| **OpenCode Zen (Free)** | `zen` | Espacio gratuito con cuota controlada. Requiere API Key válida de OpenCode. Es el único modelo gratuito autorizado a través del gateway. |
| **Local (Ollama)** | `ollama` | Contenedor local integrado en el stack (`anomalia_ollama`). Sin límite de tokens. Modelo por defecto: `llama3.2:1b` (descargado automáticamente durante el despliegue). |
| **Google Gemini API** | `gemini` | Modelo comercial basado en API Key y modelo configurable por el usuario. |

{% hint style="info" %}
Las credenciales y claves API se almacenan cifradas en la base de datos y nunca se versionan en el repositorio de código fuente.
%}{% endhint %}

---

## 2. Chat de IA con Restricción de Contexto

El endpoint `POST /api/v1/ai/chat` permite consultar al modelo de lenguaje aplicando un **aislamiento estricto por contexto** para evitar la contaminación cruzada de datos entre tenants o dominios de observabilidad.

### Contextos Permitidos y Restricciones

| Contexto (`context_type`) | Ámbito de Datos | Prompt Canónico / Restricción |
| :--- | :--- | :--- |
| `vmalert_rules` | Reglas del Tenant activo | Restringido exclusivamente a gramática PromQL y diseño de reglas vmalert. |
| `victoria_metrics_query` | Métricas generales | Limitado a sintaxis PromQL para VictoriaMetrics. |
| `victoria_logs_query` | Logs del sistema | Limitado a sintaxis LogsQL para VictoriaLogs. |
| `victoria_traces_query` | Trazas distribuidas | Limitado a consultas de trazas OTLP en VictoriaTraces. |
| `pyroscope_query` | Perfiles de rendimiento | Limitado a análisis de CPU/Memoria de Pyroscope. |
| `parses_query` | Dashboards | Limitado a la estructura y paneles JSON de Parses. |

{% hint style="warning" %}
Si el usuario realiza una pregunta fuera del ámbito autorizado para el contexto activo, el modelo responde obligatoriamente con la frase canónica de fallback: 
`"Solo puedo ayudarte con [tema permitido]."`
%}{% endhint %}
