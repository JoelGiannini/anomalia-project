# Spec 011: Tenant ABM, instancias vmalert por tenant, aislamiento tenant→instancia

Estado: draft (planificado bajo SSD)
Alcance: Alta/gestión de tenants con ciclo de vida completo: slug automático único, account_id/project_id únicos entre activos (reutilizables tras hard-delete+limpieza), X-Scope-OrgID derivado de slug UPPER sin caracteres especiales, 1 instancia vmalert por tenant (1:1), balanceo por menor número de instancias activas (manual por defecto + automático), puertos dinámicos+mapeo, reglas YAML por slug, reload /-/reload, vmagent scrape por instancia, dual-mode Ansible (dynamic|static), scopes UI vmalert por tenant + alertmanager_global vía ticket, Parses automático async, hard-delete explícito con doble confirmación + auditoría, aislamiento tenant→instancia.

## 1. Principios
- 1 vmalert por tenant (1:1). No compartido.
- Hard-delete explícito (doble confirmación). No soft-delete. 
- Operaciones largas: async BackgroundTasks + estado en BD + polling (job_state). 
- Balanceo automático = menor número de tenants activos asignados por nodo (instancia infraestructura tipo vmalert). Manual por defecto + automático.
- Slug automático, inmutable tras creación. Único con sufijo numérico ante colisión. 
- X-Scope-OrgID = slug normalizado UPPER, sin espacios, sin caracteres especiales (solo A-Z0-9_-). 
- account_id/project_id únicos entre activos; reutilizables tras hard-delete+limpieza (solo cuando no existan referencias activas). 
- Puertos dinámicos + mapeo (host_port único por nodo/host). 
- Reglas YAML: /opt/anomalia/vmalert-rules/<tenant_slug>/alert_rules.yml (o estructura por slug). 
- Reload: HTTP /-/reload por instancia vmalert. 
- Aislamiento tenant→instancia: validación estricta. Prohibido cross-tenant. 
- Alertmanager UI global vía ticket (scope alertmanager_global): requiere perfil alerts_manager (administración). TTL corto, audit, rate-limit. 
- vmalert UI por tenant vía ticket (scope vmalert por tenant). 
- vmagent scrapea cada vmalert nuevo (etiquetado tenant/instancia). 
- Dual-mode Ansible (dinámico vía infrastructure_nodes, estático via inventario).

## 2. Modelo BD (resumen)
Ver §2b para detalle completo. Principios aplicados: slug inmutable, 1:1 vmalert, hard-delete 2-step con auditoría, job_state persistente en Postgres (P1-A), balanceo menor nº instancias activas, org_id_upper derivado UPPER sin especiales.

## 2b. Modelo BD - Detalle (sincronizar database.py e init.sql.j2 / role backend/templates/init.sql.j2)

### 2b.1 tenants (ampliación)
- slug VARCHAR(100) UNIQUE (inmutable, kebab-case único con sufijo numérico). **Backfill en init.sql.j2**: los tenants sembrados (METRICS, TRACES, PROFILES, AUDIT_LOGS) reciben slug/display_name/org_id_upper vía `COALESCE(tenants.slug, EXCLUDED.slug)` en el ON CONFLICT, para que el paso 2 del hard-delete sea posible en instalaciones previas a la spec.
- display_name VARCHAR(150)
- account_id INTEGER, project_id INTEGER (unicidad entre activos)
- instance_id INTEGER REFERENCES infrastructure_nodes(id) ON DELETE SET NULL (nodo asignado para instancia vmalert)
- vmalert_node_id INTEGER REFERENCES infrastructure_nodes(id) ON DELETE SET NULL (seleccionado manual/auto)
- vmalert_port INTEGER
- has_alerts BOOLEAN DEFAULT FALSE
- placement_mode VARCHAR(10) DEFAULT 'manual' CHECK (placement_mode IN ('manual','auto'))
- status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('provisioning','active','deleting','error','deleted_cleanup'))
- org_id_upper VARCHAR(100) UNIQUE (derivado de slug UPPER, sin espacios/caracteres especiales)
- deleted_at TIMESTAMP, deletion_confirmed_at TIMESTAMP, deletion_confirmed_by INTEGER REFERENCES users(id) ON DELETE SET NULL, deletion_challenge_id VARCHAR(64)
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
Índice parcial: UNIQUE (account_id, project_id) WHERE status='active' AND deleted_at IS NULL (activos). 

### 2b.2 infrastructure_nodes (ampliación)
- roles VARCHAR(255)
- ports_pool JSON/JSONB (o TEXT) para rango/reservas
- capacity_slots INTEGER DEFAULT 10
- tenants_count_active INTEGER DEFAULT 0 (denorm, balanceo menor nº instancias activas)

### 2b.3 tenant_vmalert_instances (1:1)
- id SERIAL PRIMARY KEY
- tenant_id INTEGER UNIQUE NOT NULL REFERENCES tenants(id) ON DELETE CASCADE
- instance_id INTEGER NOT NULL REFERENCES infrastructure_nodes(id) ON DELETE RESTRICT
- port INTEGER NOT NULL
- service VARCHAR(20) DEFAULT 'vmalert'
- unit_name VARCHAR(150) NOT NULL
- rules_path VARCHAR(255) NOT NULL
- status VARCHAR(20) DEFAULT 'deployed' CHECK (status IN ('creating','deploying','deployed','error','stopped','undeployed'))
- health VARCHAR(10) DEFAULT 'unknown' CHECK (health IN ('ok','degraded','down','unknown'))
- last_deployed_at TIMESTAMP
- enabled BOOLEAN DEFAULT TRUE
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
UNIQUE (instance_id, port)

### 2b.4 job_state (persistente Postgres)
- id VARCHAR(36) PRIMARY KEY (UUID recomendado)
- type VARCHAR(30) (tenant_create, tenant_delete, vmalert_deploy, vmalert_undeploy, vmalert_reload, parses_provision)
- ref_id INTEGER
- status VARCHAR(12) DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled'))
- phase VARCHAR(30)
- progress_pct INTEGER DEFAULT 0
- logs_ref VARCHAR(255)
- error_code VARCHAR(50)
- result JSONB
- created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
- started_at TIMESTAMP, finished_at TIMESTAMP, timeout_at TIMESTAMP
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
Índices: (type,status), (ref_id), (created_at)

### 2b.5 port_mapping (puertos dinámicos+mapeo)
- id SERIAL PRIMARY KEY
- instance_id INTEGER NOT NULL REFERENCES infrastructure_nodes(id) ON DELETE RESTRICT
- tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL
- service VARCHAR(20)
- host_port INTEGER NOT NULL
- container_port INTEGER
- proto VARCHAR(5) DEFAULT 'tcp'
- purpose VARCHAR(50)
- expires_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
UNIQUE (instance_id, host_port)

### 2b.6 audit_deletions (hard-delete 2-step)
- id SERIAL PRIMARY KEY
- tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT
- actor INTEGER REFERENCES users(id) ON DELETE SET NULL
- reason TEXT
- ip VARCHAR(45), user_agent VARCHAR(255)
- challenge_id VARCHAR(64) NOT NULL UNIQUE
- confirm_step1_at TIMESTAMP, confirm_step2_at TIMESTAMP
- outcome VARCHAR(15) DEFAULT 'pending' CHECK (outcome IN ('pending','completed','expired','cancelled'))
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP



## 3. API (contratos) — F3

### 3.1 Endpoints tenants (administración)
| Método | Ruta | Auth/Profile | Descripción |
|---|---|---|---|
| GET | /api/v1/admin/tenants | tenants_manager | Listar tenants (ampliado con slug, display_name, org_id_upper, status, instance_id, vmalert_node_id, vmalert_port, has_alerts, placement_mode) |
| GET | /api/v1/admin/alerts/tenants | alerts_manager | Listado mínimo para la tarjeta Alerts (conf): id, name, slug, org_id_upper, status, instance_id, vmalert_port, has_alerts, vmalert_deployed. **No** expone account_id/project_id. Filtra `deleted_at IS NULL`. |
| POST | /api/v1/admin/tenants | tenants_manager | Crear tenant. Async (BackgroundTasks). Retorna 202 Accepted + job_id. Genera slug auto (kebab-case, inmutable, único con sufijo). Calcula org_id_upper = slug UPPER sin caracteres especiales. Selecciona instancia vmalert por balanceo menor nº instancias activas (placement_mode=auto) o usa vmalert_node_id (manual). Crea instancia vmalert 1:1. Provisiona Parses async. |
| PUT | /api/v1/admin/tenants/{tenant_id} | tenants_manager | Actualizar campos permitidos (name/display_name, has_alerts, placement_mode, vmalert_node_id, vmalert_port). slug/org_id_upper **inmutables** tras creación. |
| POST | /api/v1/admin/tenants/{tenant_id}/delete/confirm1 | tenants_manager | Hard-delete paso 1. Genera challenge_id (UUID/short), TTL 10 min (single-use, P3-A). Registra en audit_deletions (pending, actor, ip, ua, reason). Retorna {challenge_id, expires_at, tenant_slug}. Requiere doble confirmación. |
| POST | /api/v1/admin/tenants/{tenant_id}/delete/confirm2 | tenants_manager | Hard-delete paso 2. Valida challenge_id vigente/single-use, confirm_text == tenant.slug (exacto). Marca tenant.status='deleting', crea job (tenant_delete) async. Retorna 202 Accepted + job_id. |
| GET | /api/v1/admin/tenants/{tenant_id}/status | tenants_manager | Estado tenant + instancia vmalert + reglas. |
| GET | /api/v1/admin/tenants/{tenant_id}/vmalert/instance | tenants_manager | Detalle instancia vmalert (estado, health, nodo, puerto, rules_path, unit_name). |

### 3.2 Jobs (polling)
| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | /api/v1/admin/jobs/{job_id} | Autenticado (JWT) | Polling estado job_state (status: queued/running/succeeded/failed/cancelled, phase, progress_pct, logs_ref, error_code, result, started_at, finished_at). Persistente en Postgres (P1-A). |

### 3.3 Reglas vmalert por tenant
| Método | Ruta | Auth/Profile | Descripción |
|---|---|---|---|
| GET | /api/v1/admin/tenants/{tenant_id}/vmalert/rules | alerts_manager | Lee /opt/anomalia/vmalert-rules/<tenant_slug>/alert_rules.yml. Valida tenant→instancia. |
| PUT | /api/v1/admin/tenants/{tenant_id}/vmalert/rules | alerts_manager | Guarda YAML (validación sintáctica básica). Actualiza checksum. No ejecuta reload automático. |
| POST | /api/v1/admin/tenants/{tenant_id}/vmalert/reload | alerts_manager | Fuerza reload HTTP /-/reload en instancia vmalert del tenant (tenant→instancia). Async (job vmalert_reload) o directo con resultado. Retorna 202 + job_id si async. |

### 3.4 Tickets UI (proxy)
| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | /api/v1/ui/ticket | Autenticado (JWT) | Emite ticket opaco. Body: {tenant_id, scope}. Scopes soportados: metrics/logs/traces/profiling/dashboards/audit + vmalert + alertmanager_global. Gating: scopes de administración (vmalert, alertmanager_global) requieren perfil alerts_manager. Scopes de visualización/otros siguen perfiles existentes (access_*). Valida tenant_access + tenant→instancia si scope=vmalert. |
| GET/POST | /ui/redeem/{ticket} | Público (canje) | Canjea ticket, marca consumido, cookie sesión, redirect a /ui/{ticket}/. |
| (proxy) | /ui/{ticket}/* | Sesión ticket | Proxy con renovación deslizante. scope=vmalert → upstream instancia vmalert del tenant (tenant→instancia). scope=alertmanager_global → upstream Alertmanager global (sin tenant). Inyecta X-Scope-OrgID (org_id_upper derivado slug UPPER sin especiales) cuando aplique. |

### 3.5 Ciclo de vida vmalert (opcional)
| Método | Ruta | Auth/Profile | Descripción |
|---|---|---|---|
| POST | /api/v1/admin/tenants/{tenant_id}/vmalert/deploy | alerts_manager | Despliega/re-asigna instancia 1:1 (async job). |
| POST | /api/v1/admin/tenants/{tenant_id}/vmalert/undeploy | alerts_manager | Detiene instancia (estado undeployed/stopped) según política. No borra reglas (hard-delete las borra en deleted_cleanup). |
| POST | /api/v1/admin/tenants/{tenant_id}/vmalert/redeploy | alerts_manager | Redeploy (recrear unidad + reload). Async. |

### 3.6 Parses (provisión)
| Método | Ruta | Auth/Profile | Descripción |
|---|---|---|---|
| POST | /api/v1/admin/tenants/{tenant_id}/parses/provision | tenants_manager | Provisiona Parses para tenant (idempotente). Async (job parses_provision), no bloqueante (a futuro habilitado por defecto). |

Notas: operaciones largas → 202 Accepted + job_id + GET /api/v1/admin/jobs/{job_id} (polling). Hard-delete 2-step (confirm1→challenge, confirm2→202). Slug inmutable. org_id_upper derivado slug UPPER sin caracteres especiales.



## 4. Ansible (dual-mode) — F4

### 4.1 Principios dual-mode
- Flag explícito `vmalert_per_tenant: false` (default) para preservar modo single-vmalert actual (P2).
- Si `vmalert_instances` (lista por tenant) está definida y no vacía → **modo por-tenant** (1:1). Si no → **modo single** (comportamiento actual).
- Dual-mode debe ser retrocompatible: ningún cambio rompe despliegue existente.
- Backend invoca Ansible **dirigido** pasando `--extra-vars` con `vmalert_instances` (orquestación async). No requiere editar inventory.ini para operaciones por tenant.

### 4.2 Modo por-tenant: vmalert (1:1)
- Unidad systemd por instancia: `anomalia-vmalert-<tenant_slug>.service` (unit_name persistido en DB).
- Reglas por tenant: `/opt/anomalia/vmalert-rules/<tenant_slug>/alert_rules.yml` (rules_path). Directorio creado con permisos correctos.
- Puerto dinámico: `--httpListenAddr=:<port>` (host_port desde port_mapping, único por instancia/nodo).
- Targets Victoria/Alertmanager: parametrizados desde inventario dinámico o estático. `-evaluationInterval` configurable.
- Templates: `vmalert.service.j2` debe soportar iteración por `item` (instancia) en modo por-tenant; mantener ruta single cuando no iterando.
- Handlers: recarga/restart por instancia. Soporta reload HTTP `/ -/reload` (usado por backend; handler Ansible para despliegue inicial).
- Idempotente: solo recrea si cambia checksum config/unidad.

### 4.3 vmagent (scrapes iterativos)
- Añadir scrapes por instancias vmalert **activas** (`tenant_vmalert_instances.status='deployed'`, `enabled=true`, tenant activo).
- Job: `job_name: vmalert-<tenant_slug>` con `targets: ["<node_ip>:<port>"]`.
- Relabels: `tenant_id`, `tenant_slug`, `instance_id`, `org_id_upper`, `component="vmalert"`, `service="vmalert"`.
- Config regenerada ante alta/baja/reasignación de instancia. Reload vmagent tras cambios.
- Template iterativo sobre `vmalert_instances` cuando presente.

### 4.4 vmauth (regen con org_id_upper)
- Mapeos por tenant activo incluyen **X-Scope-OrgID = org_id_upper** (derivado slug UPPER sin caracteres especiales) para Pyroscope y coherente con scoping.
- Regenerar `vmauth.yml.j2` + reload ante alta/baja tenant activo. No romper mapeos existentes.
- Mantener dual-awareness (si `tenants_active` pasado vía extra-vars).

### 4.5 Puertos dinámicos + mapeo (port_mapping)
- Rango reservado `vmalert_port_range_start/end` configurable (defaults razonables). 
- Asignación transaccional: reservar host_port único por `(instance_id/nodo, host_port)`. Registrar en `port_mapping` (tenant_id, service='vmalert', purpose='tenant_vmalert', creado con expires_at null).
- Liberar puerto en **hard-delete** (paso deleted_cleanup). Reutilizar puertos liberados de instancias eliminadas.
- Balanceo automático = **menor nº instancias activas** por nodo (`tenants_count_active` denorm). Lock + recálculo tras asignación/desasignación.

### 4.6 Invocación dirigida desde backend
- Backend crea `job_state` (persistente Postgres P1-A) y ejecuta `ansible-playbook` con `--extra-vars @json` conteniendo `vmalert_instances`, `infra_mode`, `action` (deploy_tenant_vmalert/undeploy_tenant_vmalert/reload/redeploy), `tenant_id`, `tenant_slug`, `org_id_upper`.
- Respuesta 202 + job_id. Polling GET /api/v1/admin/jobs/{job_id}. Capturar stdout/stderr en job_state.logs_ref/result.

### 4.7 Hard-delete cleanup (deleted_cleanup)
- Al completar hard-delete (confirm2 job tenant_delete): detener/deshabilitar unidad `anomalia-vmalert-<slug>.service`, borrar directorio `/opt/anomalia/vmalert-rules/<tenant_slug>/` (YAML) (P4-A: borrar en deleted_cleanup), liberar host_port en `port_mapping`, actualizar `tenants_count_active` por nodo, quitar scrape vmagent, regenerar vmauth, actualizar `tenant_vmalert_instances`/estado, marcar tenant `deleted_cleanup` (o purgado) tras verificación referencias activas. Reutilización IDs tras limpieza.

### 4.8 Retrocompatibilidad (modo single)
- Si `vmalert_per_tenant=false` o `vmalert_instances` vacío: roles mantienen rutas actuales (`/etc/anomalia/vmalert/alert_rules.yml`, `anomalia-vmalert.service` único). No tocan unidades existentes. Templates con condicionales `when: vmalert_instances is defined and vmalert_instances|length>0`.
## 5. Frontend
ABM: placement manual/auto, nodo vmalert (si manual), has_alerts. 
Estado provisioning/deleting/error. 
Doble confirmación hard-delete (paso1 challenge, paso2 ingresar slug exacto). 
Alerts (conf): lista vmalert por tenant accesible + Alertmanager UI global (ticket). 
Editor YAML por tenant + Guardar + Reload.

## 5. Frontend (Vanilla JS modular) — F5

### 5.1 admin.js (ABM Tenants)
- Campos ampliados: has_alerts, placement_mode (manual|auto), vmalert_node_id (select nodos tipo vmalert, deshabilitado si auto), vmalert_port (opcional, vacío = dinámico). 
- Mostrar: slug (inmutable), org_id_upper, instance_id asignada, status (provisioning/active/deleting/error/deleted_cleanup), tenants_count_active por nodo.
- Hard-delete 2-step **en modal** (`modal-tenant-delete`): Paso 1 genera challenge_id (TTL 10 min single-use, P3-A) via POST /api/v1/admin/tenants/{id}/delete/confirm1 → muestra challenge_id + instrucción "ingresar slug exacto". Paso 2 valida confirm_text == tenant.slug → POST /api/v1/admin/tenants/{id}/delete/confirm2 → recibe 202 + job_id, inicia polling. Sin slug el tenant no se puede hard-deletar desde la UI (el backend exige coincidencia exacta).
- Acciones por tenant: Deploy/Undeploy/Redeploy Rules/Reload (condicionales por status). Estado muestra progreso (polling job).

### 5.2 api.js
Endpoints añadidos: deleteTenantConfirm1, deleteTenantConfirm2, fetchJob(job_id), tenantVmalertAction(tenantId, action) para reload/deploy/undeploy/redeploy, getTenantVmalertRules, saveTenantVmalertRules, fetchAlertsTenants (GET /api/v1/admin/alerts/tenants), createVmalertUiTicket, createAlertmanagerGlobalTicket. Todas operaciones largas esperan 202 + job_id.

### 5.3 state.js (polling centralizado)
- Mantiene mapa jobs {job_id → estado} con trackJob/updateJob/dropJob. `pollJob(jobId, onUpdate)` consulta GET /api/v1/admin/jobs/{job_id} cada 1.5s hasta succeeded/failed/cancelled (timeout 5 min). Refresca listas al completar. Persistencia lógica (cliente) basado en job_state (Postgres).

### 5.4 ui.js (Alerts conf)
- Sección "Alerts (conf)" dentro de vista alerts: lista tenants con instancia vmalert desplegada (vmalert_deployed) + botones "Abrir vmalert UI (por tenant)", "Reglas" y "Reload", más la tarjeta global de Alertmanager.
- Gating: alerts_manager para abrir UIs de administración (vmalert/alertmanager_global). access_alerts para visualización de alertas/IA.
- Listado vía `api.fetchAlertsTenants()` (GET /api/v1/admin/alerts/tenants, gated por alerts_manager, sin tenants_manager).
- Tickets: scope "vmalert" (por tenant) → POST /api/v1/ui/ticket {tenant_id, scope:'vmalert'}; scope "alertmanager_global" → createAlertmanagerGlobalTicket (sin tenant_id). Mostrar org_id_upper/estado/puerto/nodo.
- Los botones Reglas/Reload se wirean por delegación en main.js sobre el contenedor estático #alerts-config-list (se recrean en cada render).

### 5.5 index.html
Contenedores: #alerts-config-container (Alerts conf), #modal-tenant-delete (hard-delete 2 pasos) y #modal-vmalert-rules (editor YAML). Mantener estructura modular.

### 5.6 Editor YAML
Textarea (`#vmalert-rules-yaml`) por tenant para /vmalert/rules. Botones Guardar (PUT) + Guardar y recargar (PUT + POST /reload con polling). Estado visible en #vmalert-rules-status.

### 5.7 Consolas de administración vía UI proxy (scopes `vmalert` y `alertmanager_global`)

Ambos scopes abren una consola **de administration**, no de visualización: exigen perfil
`alerts_manager` (P5) en la emisión del ticket **y en cada request del proxy**.

Upstreams (resueltos desde `infrastructure_nodes`, nunca desde parámetros del cliente):

| Scope | Upstream | Origen | Tenant |
|---|---|---|---|
| `vmalert` | `http://<service_ip o ip_address>:<port>` | `tenant_vmalert_instances` JOIN `infrastructure_nodes` | obligatorio: `tenant_vmalert_instances.tenant_id` |
| `alertmanager_global` | `http://<service_ip o ip_address>:<port>` | `infrastructure_nodes WHERE component_type='alertmanager' AND is_active` | ninguno |

Reglas de aislamiento y seguridad:
- El scope `vmalert` **valida tenant→instancia en el servidor**: la instancia se resuelve por
  `tenant_vmalert_instances.tenant_id`, nunca por un `instance_id` que venga del cliente. Sin
  instancia `deployed` + `enabled` para un tenant `active` → **409**.
- `alertmanager_global` es la única consola sin tenant: por eso `ui_tickets.tenant_id` pasa a
  **nullable**. El ticket se emite sin `tenant_id` y el canje monta la consola en la raíz del
  ticket, igual que Parses.
- Ambas consolas son de **solo lectura**: se rechazan `PUT/PATCH/DELETE` (mismo criterio que las
  consolas de Victoria). No se inyecta `X-Scope-OrgID` ni scoping de Victoria.
- Guardas de ruta: se reutiliza `_reject_path_traversal` (`://` y `..` prohibidos). El prefijo
  siempre lo compone el servidor a partir del upstream resuelto; el cliente nunca elige destino.
- Sesión: con cookie, `_authorize_session` compara `tenant_id` del ticket (NULL en el scope
  global, NULL en la cookie → coincide). Con JWT, el acceso al tenant se valida para `vmalert`;
  en el scope global se omite `verify_tenant_access` (no hay tenant) y el control pasa a ser el
  re-chequeo del perfil `alerts_manager` contra `user_roles → role_profiles → profiles`.
- `service_ip` se prefiere sobre `ip_address` (misma convención que el resto del ABM de nodos).

Contrato de la petición de ticket:

```jsonc
// vmalert (por tenant)
{"tenant_id": 7, "scope": "vmalert"}
// alertmanager_global (sin tenant)
{"scope": "alertmanager_global"}
```

## 6c. Validaciones, idempotencia y errores
- Slug inmutable tras creación. org_id_upper derivado slug UPPER sin especiales, único.
- account_id,project_id únicos entre activos (índice parcial). Reutilizables tras hard-delete+limpieza (solo referencias activas verificadas).
- tenant→instancia validado en deps/proxy (nunca params cliente).
- Path traversal: slug normalizado [a-z0-9-]+.
- Reload /-/reload: timeout + validación YAML + healthcheck + retry.
- Balanceo: lock + denorm tenants_count_active + menor nº instancias activas.
- Puertos: UNIQUE(instance_id,host_port), reserva transaccional, reutilización tras cleanup.
- Hard-delete 2-step: challenge TTL 10min single-use, confirm_text==slug exacto, audit completo.
- Async: 202+job_id, polling con timeout, estados bien definidos, job_state persistente (P1-A).
- Dual-mode retrocompat: condicionales preservan single-vmalert.
- Los `HTTPException` levantados dentro de un `try` se reenvían con su status original (`except HTTPException: raise`); el `except Exception` genérico no debe capturarlos (evita 400 con detalle duplicado "400: 404: ...").
- Los args de `cursor.execute` con un solo valor llevan coma: `(tenant_id,)`; sin coma psycopg2 recibe un int y falla con `TypeError: 'int' object does not support indexing`.
- `_node_base_url(ip, port, default_port)` recibe 3 args: en `_resolve_alertmanager_upstream` el fallback es `service_ip or ip_address`, no 4 args posicionales.
## 6. Seguridad/validación
tenant→instancia validado en deps/proxy. X-Scope-OrgID inyectado solo válido. Puertos dinámicos acotados por pool. Path traversal mitigado por slug validado. Audit hard-delete 2-step. Rate-limit + TTL tickets global. 

## 6b. Gating por perfiles
- access_alerts: visualización de alertas que llegan de Alertmanager + análisis de IA en tarjetas del backend.
- alerts_manager: administración de vmalert y Alertmanager (configuración, reglas, instancias vmalert por tenant, acceso a UIs de administración alertmanager_global y vmalert por tenant).

## 7. Fases SSD (obligatorio)

0. Leer specs 001–011, `constitution.md`, `AGENTS.md`. Cargar skills: `anomalia-backend-skill`, `anomalia-ansible-skill`, `anomalia-frontend-validator`. Verificar estado git.
1. Consolidar 011 con 002/005/008/010. Ajustes P1–P6 aplicados. Mantener spec 011 (draft) actualizado.
2. Modelo BD detallado (§2b): sincronizar `database.py` e `init.sql.j2` (role `backend/templates/init.sql.j2`) con columnas/tablas nuevas, índices parciales, CHECKs. job_state persistente Postgres (P1-A).
3. Contratos API + flujo async (F3): 202+job_id + polling `GET /api/v1/admin/jobs/{job_id}`, hard-delete 2-step (confirm1 TTL 10min single-use P3-A, confirm2 valida slug exacto). ticketing con scopes vmalert/alertmanager_global + gating alerts_manager (P5).
4. Ansible dual-mode (F4): vmalert 1:1 por tenant, unidades `<slug>`, reglas por slug, vmagent scrapes iterativos, vmauth regen con org_id_upper, puertos dinámicos+mapeo, invocación dirigida, hard-delete cleanup (YAML borrado en deleted_cleanup P4-A). Retrocompat modo single.
5. Frontend modular (F5): modal 2-step hard-delete, polling centralizado `state.js`, Alerts (conf), editor YAML+reload, gating correcto.
6. Verificación: lint/tests + aislamiento tenant→instancia + 2-step + polling async + balanceo menor nº instancias + slug inmutable + org_id_upper derivado UPPER sin especiales + reuse IDs tras cleanup + dual-mode + puertos+mapeo.
7. Post-cambio: actualizar specs/AGENTS.md/docs según SSD. Recordar destroy+deploy solo si cambia código infra/compose (no docs). Prohibido commit/push autónomo (constitution).

## 8. Riesgos + mitigaciones (aplicados)

| Riesgo | Mitigación |
|---|---|
| Hard-delete accidental | Doble confirmación (confirm1 challenge_id TTL 10min single-use P3-A, confirm2 requiere tenant.slug exacto), auditoría completa (audit_deletions), bloqueo si referencias activas. |
| Colisiones slug/org_id_upper | Auto-generación única con sufijo numérico, normalización, UPPER sin especiales, slug inmutable (P6-A), unicidad org_id_upper. |
| Reutilización IDs prematura | Gate por `deleted_cleanup` + verificación referencias activas. Índice parcial activos (account_id,project_id). |
| Race balanceo | Transacción + lock + `tenants_count_active` denorm + menor nº instancias activas (P3 placement auto). |
| Puertos conflicto | Pool dinámico + reserva transaccional + UNIQUE(instance_id,host_port), reutilización tras cleanup. |
| Reload YAML inválido | Validación sintáctica previa, checksum, backup lógico, timeout + healthcheck + retry. |
| Dual-mode drift | Flag explícito `vmalert_per_tenant` default false (P2), condicionales + detección por `vmalert_instances`, retrocompat. |
| Fuga tenant→instancia | Validación estricta en deps/proxy (nunca params cliente), scope ticket por tenant, middleware org_id_upper. |
| Alertmanager_global abuso | Requiere perfil `alerts_manager` (P5), TTL corto, rate-limit, audit, one-time ticket. |
| Pérdida estado jobs | `job_state` persistente en Postgres (P1-A), idempotency, timeout, recovery. |
| YAML retenido | Borrado en `deleted_cleanup` (P4-A), limpieza completa en hard-delete. |

