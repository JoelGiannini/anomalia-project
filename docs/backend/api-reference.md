# Referencia de API Backend

El backend expone una API RESTful construida con **FastAPI**, protegida mediante autenticación basada en tokens JWT/OIDC y control de acceso basado en roles y perfiles (`RBAC`).

---

## 📋 Resumen de Routers Principales

| Prefijo | Módulo | Descripción |
| :--- | :--- | :--- |
| `/api/auth` | Autenticación | Gestión de sesiones y tokens de acceso. |
| `/api/admin` | Administración | Gestión de usuarios, roles, perfiles y tenants (`tenants_manager`). |
| `/api/infrastructure` | Infraestructura | Control y estado de nodos de infraestructura (`infrastructure_nodes`). |
| `/api/v1/tenants` | Tenants | Endpoints puente para consulta de tenants autorizados. |
| `/api/v1/ui` + `/ui` | Proxy Consolas | Proxy autenticado con tickets deslizantes para las UIs de VictoriaMetrics, Traces, Logs, Pyroscope y Parses. |
| `/api/v1/ai` | Inteligencia Artificial | Chat asistente contextual y gestión de proveedores LLM. |

---

## 🔌 Endpoints Destacados

### 1. Sincronización y Materialización de Reglas vmalert
* **Ruta:** `POST /api/v1/admin/tenants/{tenant_id}/vmalert/sync_rules`
* **Permisos Requeridos:** `alerts_manager`
* **Descripción:** Encola un trabajo asíncrono (`vmalert_sync_rules`) que lee el campo `rules_yaml` desde la base de datos (fuente de verdad), lo materializa en la ruta del nodo correspondiente (`rules_path`) y ejecuta un `/-/reload` HTTP sobre la instancia vmalert.
* **Respuesta Exitosa (`202 Accepted`):**
  ```json
  {
    "status": "accepted",
    "job_id": "b5a41a31-62c7-4f81-9b19-c45472877a11"
  }
  ```

### 2. Chat Asistente con IA Restringida
* **Ruta:** `POST /api/v1/ai/chat`
* **Permisos Requeridos:** Token JWT válido (`verify_any_user_token`)
* **Payload de Entrada:**
  ```json
  {
    "context_type": "vmalert_rules",
    "tenant_id": 1,
    "message": "¿Cómo escribo una regla PromQL para detectar uso de CPU superior al 90%?"
  }
  ```
* **Respuesta Exitosa (`200 OK`):**
  ```json
  {
    "response": "Para detectar un uso de CPU superior al 90%, puedes utilizar la siguiente regla en vmalert:\n\n- alert: HighCpuUsage\n  expr: sum(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) by (instance) < 0.1\n  for: 5m..."
  }
  ```

---

## 🚨 Códigos de Error HTTP Comunes

| Código | Significado | Causa Habitual |
| :--- | :--- | :--- |
| `400 Bad Request` | Petición inválida | Sintaxis YAML incorrecta al guardar reglas vmalert. |
| `401 Unauthorized` | No autenticado | Token JWT ausente, vencido o malformado. |
| `403 Forbidden` | Acceso denegado | El usuario carece del perfil o rol necesario para la acción. |
| `404 Not Found` | No encontrado | El tenant, nodo o recurso solicitado no existe. |
| `409 Conflict` | Conflicto de estado | Intento de modificar o eliminar un tenant de control interno (`is_internal=true`) o instancia inexistente. |
