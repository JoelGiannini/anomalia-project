# Tenants de Control Interno y Reglas Canónicas

{% hint style="info" %}
Los tenants de control interno (`is_internal = true`) garantizan que la infraestructura base del sistema esté permanentemente monitoreada, sin depender de la edición manual de reglas por parte de los operadores.
%}{% endhint %}

---

## 1. Motivación y Concepto

En una plataforma de observabilidad de nivel empresarial, los componentes críticos del stack (métricas generales, trazas, perfiles de rendimiento y registros de auditoría) deben contar con alertas críticas nativas e inquebrantables. 

Para lograr esto, Anomalia define cuatro dominios internos protegidos:
- **`METRICS`** (`type = "metrics"`): Supervisión general de VictoriaMetrics y salud del backend.
- **`TRACES`** (`type = "logs" / "traces"`): Disponibilidad y latencia de VictoriaTraces.
- **`PROFILES`** (`type = "profiles"`): Salud de Pyroscope y recolección de perfiles de CPU/Memoria.
- **`AUDIT_LOGS`** (`type = "logs"`): Integridad y flujo de VictoriaLogs y pistas de auditoría.

---

## 2. El Flag `is_internal = true`

Cada uno de estos tenants se inicializa con el flag `is_internal = true` a través de los scripts de migración y siembra inicial (`init.sql.j2` / `database.py`).

| Característica | Tenants Estándar | Tenants de Control Interno (`is_internal = true`) |
| :--- | :--- | :--- |
| **Creación** | Manual (vía Panel Admin o API) | Automática por siembra del sistema |
| **Edición de Reglas** | Completamente libre por API / UI | **Bloqueada (409 Conflict)** |
| **Placement** | Manual o Automático configurable | Automático (*Always-On*) |
| **Fuente de Reglas** | Definidas por el usuario | Reglas Canónicas inmutables en código |

---

## 3. Reglas Canónicas Inmutables (SSOT en Código)

Las reglas de alerta para estos tenants residen físicamente en el repositorio del backend:
`backend/app/internal_rules/<slug>.yaml`

{% hint style="warning" %}
Estos archivos se cargan mediante validación `yaml.safe_load` y se inyectan **verbatim** (sin procesar plantillas Jinja sobre PromQL para evitar corrupciones en las llaves `{{ $labels.* }}`).
%}{% endhint %}

### Flujo de Bootstrap y Despliegue (*Always-On*)

1. **Arranque del Worker (`VmalertWorker._bootstrap_internal`):**
   - Al iniciar el ciclo del worker, se escanean los tenants activos con `is_internal=true`.
   - Si no poseen una instancia vmalert activa (`status='deployed'`) ni un trabajo en cola, el sistema selecciona automáticamente el nodo con menor carga (`capacity_slots` / `tenants_count_active`).
   - Se encola un trabajo de tipo `vmalert_deploy` aplicando la regla canónica correspondiente.

2. **Inmutabilidad:**
   - Si un operador intenta modificar las reglas mediante `PUT /api/v1/admin/tenants/{id}/vmalert/rules`, la API responde con un código **`409 Conflict`** indicando que el tenant es de control interno.
   - De igual forma, las operaciones destructivas (hard-delete o undeploy) sobre estos tenants están protegidas y prohibidas por el validador `_guard_internal_tenant`.

---

## 4. Interfaz de Usuario (UI)

En el panel de administración web:
- El editor de reglas YAML para tenants internos se abre automáticamente en modo **solo lectura** (`readOnly`).
- Se muestra un distintivo visual (*badge*): **"Control interno · reglas canónicas e inmutables"**.
- Los botones de guardado directo y sincronización se mantienen deshabilitados para prevenir modificaciones accidentales.
