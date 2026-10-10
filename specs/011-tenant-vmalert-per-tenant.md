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
- Reglas YAML: BD (`tenant_vmalert_instances.rules_yaml`) como fuente de verdad; materializadas en el nodo en `/etc/anomalia/vmalert/<tenant_slug>/alert_rules.yml` (rules_path). 
- Reload: HTTP /-/reload por instancia vmalert. Healthcheck previo GET /health (vmalert responde 400 a /-/health "unsupported path requested"; /-/health es de vmauth/vmagent). 
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
- is_internal BOOLEAN DEFAULT FALSE (spec §4.9: tenants de control interno; reglas canónicas inmutables y vmalert always-on)
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
- rules_yaml TEXT (fuente de verdad de las reglas; NULL hasta primer guardado)
- status VARCHAR(20) DEFAULT 'deployed' CHECK (status IN ('creating','deploying','deployed','error','stopped','undeployed'))
- health VARCHAR(10) DEFAULT 'unknown' CHECK (health IN ('ok','degraded','down','unknown'))
- last_deployed_at TIMESTAMP
- enabled BOOLEAN DEFAULT TRUE
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
UNIQUE (instance_id, port)

### 2b.4 job_state (persistente Postgres)
- id VARCHAR(36) PRIMARY KEY (UUID recomendado)
- type VARCHAR(30) (tenant_create, tenant_delete, vmalert_deploy, vmalert_undeploy, vmalert_reload, vmalert_sync_rules, vmalert_regen_scrapes, parses_provision)
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
| GET | /api/v1/admin/tenants/{tenant_id}/vmalert/rules | alerts_manager | Lee `rules_yaml` desde `tenant_vmalert_instances` (BD = fuente de verdad). Valida tenant→instancia (409 si inexistente). |
| PUT | /api/v1/admin/tenants/{tenant_id}/vmalert/rules | alerts_manager | Guarda YAML en BD (`rules_yaml`) con validación sintáctica PyYAML (400 si inválido). No ejecuta reload automático. 409 si el tenant no tiene instancia. **409 si `is_internal=true`** (§4.9): reglas de control interno no modificables por API. |
| POST | /api/v1/admin/tenants/{tenant_id}/vmalert/reload | alerts_manager | Fuerza reload HTTP `/-/reload` en instancia vmalert del tenant (tenant→instancia). Async (job `vmalert_reload`). Retorna 202 + job_id. |
| POST | /api/v1/admin/tenants/{tenant_id}/vmalert/sync_rules | alerts_manager | Encola job `vmalert_sync_rules`: materializa `rules_yaml` (BD) en `rules_path` del nodo y recarga vmalert (`/-/reload`). Retorna 202 + job_id. 422/409 si el tenant no tiene reglas o instancia. |

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
- Flag explícito `vmalert_per_tenant: false` (default del rol) para preservar modo single-vmalert actual (P2). **Implementado:** `deploy-infra.yml` fuerza `vmalert_per_tenant: true` al invocar el rol `vmalert`, así el deploy base siempre aplica la convergencia por-tenant (limpieza de unit single, §4.8) y el rol solo crea la unit single cuando el flag es `false` (sin ventana de creación+borrado en deploy limpio).
- Si `vmalert_instances` (lista por tenant) está definida y no vacía → **modo por-tenant** (1:1). Si no → **modo single** (comportamiento actual).
- Dual-mode debe ser retrocompatible: ningún cambio rompe despliegue existente.
- Backend invoca Ansible **dirigido** pasando `--extra-vars` con `vmalert_instances` (orquestación async). No requiere editar inventory.ini para operaciones por tenant.

### 4.2 Modo por-tenant: vmalert (1:1)
- Unidad systemd por instancia: `anomalia-vmalert-<tenant_slug>.service` (unit_name persistido en DB).
- Reglas por tenant: BD `rules_yaml` como fuente de verdad → materializadas en `/etc/anomalia/vmalert/<tenant_slug>/alert_rules.yml` (rules_path) por el deploy o por el job `sync_rules`. Copia vía `ansible.builtin.copy` con `src` (archivo temporal provisto por el worker vía `vmalert_rules_files`), nunca `content`, para no evaluar Jinja sobre PromQL `{{ }}`. Directorio creado con permisos correctos.
- **Canal separado de reglas (fix espec 011 §4.2):** el `rules_yaml` **no** viaja dentro de los dicts de `vmalert_instances`. Ansible templa recursivamente una variable cuando aparece en cualquier `when` del playbook (ej. `install-binaries.yml` §4b: `when: vmalert_instances is defined and vmalert_instances | length > 0`), y un `{{ $labels.job }}` anidado rompía la tarea con `AnsibleError: unexpected char '$'` (falla determinista observada en el deploy de los tenants internos). Por eso el worker pasa las reglas por el parámetro aparte `vmalert_rules` (lista `{tenant_slug, rules_yaml, rules_path}` → extra-var `vmalert_rules_files` con rutas a archivos temporales), y `vmalert_instances` queda solo con datos planos (slug, port, urls, rules_path).
- Puerto dinámico: `--httpListenAddr=:<port>` (host_port desde port_mapping, único por instancia/nodo).
- Targets Victoria/Alertmanager: parametrizados desde inventario dinámico o estático. `-evaluationInterval` configurable.
- Templates: `vmalert.service.j2` debe soportar iteración por `item` (instancia) en modo por-tenant; mantener ruta single cuando no iterando.
- Handlers: recarga/restart por instancia. Soporta reload HTTP `/ -/reload` (usado por backend; handler Ansible para despliegue inicial).
- Idempotente: solo recrea si cambia checksum config/unidad.

### 4.3 vmagent (scrapes iterativos)
- Añadir scrapes por instancias vmalert **activas** (`tenant_vmalert_instances.status='deployed'`, tenant activo).
- Job: `job_name: vmalert-<tenant_slug>` con `targets: ["<node_ip>:<port>"]`.
- Relabels: `tenant_id`, `tenant_slug`, `instance_id`, `org_id_upper`, `component="vmalert"`, `service="vmalert"`.
- **Regen incremental (job `vmalert_regen_scrapes`)**: se encola automáticamente al terminar `vmalert_deploy`/`vmalert_undeploy` y regenera la config completa de vmagent (scrapes base + por-tenant) y vmauth sobre sus nodos vía playbook `sync-scrapes.yml` (no descarga binarios). Refleja el conjunto completo de instancias, no solo el tenant disparador; no re-encola nada (la cadena termina). Idempotente.
- **Modo flat (dirigido)**: el worker inyecta `infra_components` (BD como fuente de verdad, spec 005) y `vmalert_instances` como extra-vars; `vmagent.yaml.j2`/`vmauth.yml.j2` renderizan desde esos datos cuando `infra_components` está definido (el inventario ad-hoc `-i {ip},` no expone grupos/hostvars). El `vmagent.service.j2` recibe `vmagent_remote_write_url` por extra-var en ese modo. El modo inventario queda intacto y produce la misma config.
- Template iterativo sobre `vmalert_instances` cuando presente (ambos modos).

### 4.4 vmauth (regen con org_id_upper)
- Mapeos por tenant activo incluyen **X-Scope-OrgID = org_id_upper** (derivado slug UPPER sin caracteres especiales) para Pyroscope y coherente con scoping.
- Regenerar `vmauth.yml.j2` + reload ante alta/baja tenant activo (mismo job `vmalert_regen_scrapes` del §4.3; `infra_components` inyecta vminsert/vtinsert/vlinsert/pyroscope en modo flat). No romper mapeos existentes.
- Mantener dual-awareness (si `tenants_active` pasado vía extra-vars; el regen flat usa `infra_components`).

### 4.5 Puertos dinámicos + mapeo (port_mapping)
- **Puerto determinístico por tenant:** cada tenant usa `8880 + tenant_id` (METRICS=8881, TRACES=8882, AUDIT_LOGS=8884, ...; **PROFILES queda libre**: no lleva vmalert, §4.6). Es idempotente y elimina la carrera entre workers concurrentes (spec 013); el deploy **fuerza siempre** ese puerto en `tenants.vmalert_port` y, si otro tenant ya ocupa el puerto en el mismo nodo, cae al pool por-tenant como fallback defensivo.
- **el 8880 queda reservado a la unit single** (`anomalia-vmalert.service`). Los 4 tenants default ocupan 8881-8884.
- **Reconciliación al arranque (`_bootstrap_internal`):** si `tenants.vmalert_port` (o el puerto de instancia) difiere de `8880+tenant_id` (colisión histórica 8881/8881, puerto heredado del pool), se corrige la BD y se encola `vmalert_redeploy` si la instancia está desplegada; confluencia automática sin intervención manual.
- Asignación transaccional: reservar host_port único por `(instance_id/nodo, host_port)`. Registrar en `port_mapping` (tenant_id, service='vmalert', purpose='tenant_vmalert', creado con expires_at null).
- Liberar puerto en **hard-delete** (paso deleted_cleanup). Reutilizar puertos liberados de instancias eliminadas.
- Balanceo automático = **menor nº instancias activas** por nodo (`tenants_count_active` denorm). Lock + recálculo tras asignación/desasignación.

### 4.6 Invocación dirigida desde backend
- Backend crea `job_state` (persistente Postgres P1-A) y ejecuta `ansible-playbook` con `--extra-vars @json` conteniendo `vmalert_instances`, `infra_mode`, `action` (deploy_tenant_vmalert/undeploy_tenant_vmalert/reload/redeploy), `tenant_id`, `tenant_slug`, `org_id_upper`.
- **Timeout del playbook:** `VMALERT_PLAYBOOK_TIMEOUT_SECONDS` (default 600, env-overridable). El primer deploy en frío tarda ~5 min; un límite de 300s hardcodeado mató el deploy de METRICS antes de crear la unit (ver §4.9). Si el job expira, queda `failed` y la reconciliación periódica (§4.9) lo re-encola en <60s.
- **Datasources cluster URL por-tenant:** vmselect/vminsert CLUSTER solo aceptan un segmento `<account>:<project>` (dos puntos): `--datasource.url`/`--remoteRead.url = http://<vmselect>:8401/select/0:0/prometheus` y `--remoteWrite.url = http://<vminsert>:8400/insert/0:0/prometheus`. La forma con barra (`/select/0/0/prometheus`) responde 400 (`unsupported path requested`), igual que las raíces desnudas (spec 008 §2, validado contra el binario v1.153.0-cluster). El worker resuelve la ds por-tenant (`_resolve_tenant_datasources`): **internos → store METRICS 0:0** (sus reglas canónicas consultan las métricas de stack que vmagent deposita en el tenant METRICS, aunque TRACES/AUDIT_LOGS tengan project propio 1/3); **no internos con account/project → su propio `account:project`**; fallback defensivo 0:0 + warning.
- **Pyroscope NO lleva vmalert (type='profiles'):** los perfiles no son series PromQL y Pyroscope no expone una API compatible con Prometheus HTTP API (`/api/v1/query` → 404), requerimiento del `-datasource.url` de vmalert. El monitoreo básico de Pyroscope se hace sobre el store METRICS (reglas `PyroscopeDown`/`PyroscopeHeartbeatMissing` de `internal_rules/metrics.yaml`, evaluadas por el vmalert del tenant METRICS). El worker salta el deploy/sync/auto-placement para estos tenants, la reconciliación retira instancias residuales (undeploy + limpieza de `vmalert_node_id`/`vmalert_port`), y los endpoints `POST .../vmalert/deploy|redeploy` responden 400.
- Respuesta 202 + job_id. Polling GET /api/v1/admin/jobs/{job_id}. Capturar stdout/stderr en job_state.logs_ref/result.

### 4.7 Hard-delete cleanup (deleted_cleanup)
- Al completar hard-delete (confirm2 job tenant_delete): detener/deshabilitar unidad `anomalia-vmalert-<slug>.service`, borrar directorio `/etc/anomalia/vmalert/<tenant_slug>/` (YAML) (P4-A: borrar en deleted_cleanup), liberar host_port en `port_mapping`, actualizar `tenants_count_active` por nodo, quitar scrape vmagent, regenerar vmauth, actualizar `tenant_vmalert_instances`/estado, marcar tenant `deleted_cleanup` (o purgado) tras verificación referencias activas. Reutilización IDs tras limpieza.

### 4.8 Retrocompatibilidad (modo single)
- Si `vmalert_per_tenant=false` (default del rol, solo vía invocación manual sin vars) y `vmalert_instances` vacío: roles mantienen rutas actuales (`/etc/anomalia/vmalert/alert_rules.yml`, `anomalia-vmalert.service` único). No tocan unidades existentes. Templates con condicionales `when: vmalert_instances is defined and vmalert_instances|length>0`.
- **Flag forzado en el deploy (implementado):** `deploy-infra.yml` pasa `vars: vmalert_per_tenant: true` al rol `vmalert`. Con el flag en `true`, el bloque de limpieza/convergencia se ejecuta siempre (aunque `vmalert_instances` esté vacío) y la creación de la unit single queda condicionada a `not vmalert_per_tenant`: en instalación limpia **nunca se crea** el single, eliminando la ventana que lo creaba para borrarlo después (y con ella el estado `up==0` transitorio del rol).
- **Paths cluster en la rama single:** `vmalert.service.j2` usa en ambas ramas (single y por-tenant) `--datasource.url`/`--remoteRead.url = /select/0:0/prometheus` y `--remoteWrite.url = /insert/0:0/prometheus` (§4.6): la forma con barra responde 400 en builds cluster.
- **Convergencia en modo por-tenant:** cuando `vmalert_instances` no está vacío, el role también detiene/deshabilita y elimina la unit single `anomalia-vmalert.service` y su archivo plano `/etc/anomalia/vmalert/alert_rules.yml` (idempotente, tolera ausencia; el directorio `/etc/anomalia/vmalert/` se conserva porque aloja los subdirectorios por-tenant). Al volver a modo single (instancias vacías) se recrean.
- **Convergencia por archivos en "Modo single":** aunque `vmalert_instances` esté vacío (ej. `deploy-infra.yml` sin extra-vars), el role detecta unidades `<node>/etc/systemd/system/anomalia-vmalert-*.service` con `find`; si existen por-tenant, **no crea el single** y aplica la misma limpieza (convergencia por estado del nodo, no solo por extra-vars). El single solo se crea en instalación limpia (sin unidades por-tenant) y con `vmalert_state=present`. El handler `Recargar systemd y reiniciar vmalert` es tolerante a unit ausente (`failed_when` con `msg | lower` permite `could not find the requested service`/`does not exist`): la unit puede desaparecer por un deploy por-tenant del worker entre el `notify` y el flush de handlers.
- **Teardown por-tenant idempotente (spec 013):** `destroy-infra.yml` enumera con `find` las unidades derivadas `anomalia-vmalert-*.service` (cualquier slug) y las detiene, deshabilita y elimina **antes** del `daemon_reload`, sin hardcodear nombres. `deploy-infra.yml` solo ejecuta el role `vmalert` en hosts del grupo `vmalert_nodes`. El aprovisionamiento programático del worker (play `install-binaries.yml`, §4b) despliega instancias por-tenant únicamente en hosts de `vmalert_nodes`, salvo el caso ad-hoc del propio worker (`-i <ip>,`, `groups['all'] | length == 1`).

### 4.9 Tenants de control interno (reglas canónicas inmutables)
- **Motivación:** los tenants default (METRICS, TRACES, PROFILES, AUDIT_LOGS) son el control interno de la app: cualquier fallo crítico en la infraestructura debe disparar alerta a Alertmanager. Su monitoreo no puede depender de edición manual.
- **Flag `is_internal=true`:** seed de `init.sql.j2` (y backfill `database.py`) fuerza `has_alerts=true`, `is_internal=true`, `placement_mode='auto'` en cada deploy (ON CONFLICT UPDATE). No es editable por la API (no está en `TenantPayload`).
- **Reglas canónicas en código (SSOT):** `backend/app/internal_rules/<slug>.yaml` (metrics=stack VictoriaMetrics+app+salud de Pyroscope, traces=VictoriaTraces, audit-logs=VictoriaLogs). El tenant PROFILES **no tiene vmalert** (Pyroscope ≠ PromQL, §4.6), por lo que su salud se monitorea desde las reglas de `metrics.yaml` (mismas métricas scrapeadas por vmagent al store METRICS). Deben ser archivos estáticos copiados **verbatim** (fuera de `roles/*/templates`, sin `template:` ni Jinja) para que las anotaciones `{{ $labels.* }}` lleguen intactas a vmalert; se validan con `yaml.safe_load` en el import (`internal_rules.py`).
- **Deploy canónico:** en `solo_deploy_vmalert`, si `is_internal=true` la instancia recibe **siempre** `INTERNAL_RULES[slug]` (pisa en cada deploy, incluso redeploy) y se persiste en `rules_yaml`. El único origen admisible es el código → inmutable por construcción.
- **Bootstrap always-on (VmalertWorker.start → `_bootstrap_internal`):** idempotente; para cada tenant interno `status='active'` **que no sea `type='profiles'`** sin instancia `deployed` ni job `vmalert_deploy` queued/running: auto-placement (menor `tenants_count_active`, mismo criterio que §4.2), `has_alerts=true`, encola `vmalert_deploy` (cadena normal → regen). Cubre instalaciones previas y recuperación tras fallo. Para tenants `type='profiles'`, en cambio, retira cualquier instancia residual (encola `vmalert_undeploy` mientras exista `deployed` y limpia `vmalert_node_id`/`vmalert_port` cuando desaparece).
- **Reconciliación periódica (§4.6):** `_bootstrap_internal` no corre solo al arrancar: un task dedicado (`_reconcile_loop`) lo repite cada `interval` del worker. Un deploy que falla después del bootstrap inicial (p. ej. timeout de playbook, §4.6) se re-encola automáticamente en <60s sin reiniciar contenedores; la misma pasada reconcilia deriva de puerto determinístico (§4.5). Los guards de idempotencia (instancia `deployed`, job queued/running, `succeeded`) evitan bucles de re-deploy.
- **Bloqueos API (409):** `PUT .../vmalert/rules`, `DELETE /tenants/{id}` (borrado duro + soft) y `PASOS confirm1/confirm2` del hard-delete, y `POST .../vmalert/undeploy` sobre `is_internal=true`. Helper `_guard_internal_tenant`. Quedan permitidos: GET rules (visible), sync_rules, reload, deploy/redeploy y PUT genérico de tenant (campos no críticos).
- **UI:** el editor de reglas se abre en solo-lectura (textarea `readOnly`, botones Guardar/Guardar+recargar deshabilitados) + badge "Control interno · reglas canónicas e inmutables".
- **Sin overlap en modo por-tenant:** al existir `vmalert_instances`, la unit single `anomalia-vmalert.service` no se despliega: el role la detiene, deshabilita y elimina (junto a su archivo plano `/etc/anomalia/vmalert/alert_rules.yml`), evitando el `up==0` genérico duplicado; las reglas internas por dominio cubren sus componentes con detalle. El single se recrea solo en modo single (sin instancias, §4.8).
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
- Listado vía `api.fetchAlertsTenants()` (GET /api/v1/admin/alerts/tenants, gated por alerts_manager, sin tenants_manager). El endpoint **excluye el tenant interno `profiles`** (`AND t.type <> 'profiles'` en el WHERE base, cubre `?mine=true`): Pyroscope nunca lleva vmalert (§4.6/§4.9) y nace con `has_alerts=true` por el seed interno; mostrarlo con botón "Reglas" es engañoso.
- **Progreso de despliegue y espera única (`wait_deployed`, spec 011 §5.4):** el endpoint expone mediante `LEFT JOIN LATERAL` sobre `job_state` el estado del último job de vmalert (`vmalert_job_status`, `vmalert_job_phase`, `vmalert_job_progress`). Si un tenant activo con alertas no tiene instancia `deployed` aún (p. ej. tras un destroy+deploy en frío), la UI muestra una **barra de progreso indeterminada animada** (`animate-pulse`) junto al estado/fase de despliegue ("Desplegando… FASE · X%"). En lugar de refrescar la lista periódicamente cada 10s, la UI realiza **una única petición con espera síncrona corta** (`?wait_deployed=true`, bucle interno de hasta 600s en short-transactions con re-consultas cada 3s en threadpool) que bloquea hasta que todas las instancias pendientes estén desplegadas (o expira el timeout y permite reintentar manualmente). La espera es cancelable mediante `AbortController` al cambiar de pestaña.
- Tickets: scope "vmalert" (por tenant) → POST /api/v1/ui/ticket {tenant_id, scope:'vmalert'}; scope "alertmanager_global" → createAlertmanagerGlobalTicket (sin tenant_id). Mostrar org_id_upper/estado/puerto/nodo.
- Los botones Reglas/Reload se wirean por delegación en main.js sobre el contenedor estático #alerts-config-list (se recrean en cada render).

### 5.5 index.html
Contenedores: #alerts-config-container (Alerts conf), #modal-tenant-delete (hard-delete 2 pasos) y #modal-vmalert-rules (editor YAML). Mantener estructura modular.

### 5.6 Editor YAML
Textarea (`#vmalert-rules-yaml`) por tenant. Botones: "Guardar reglas" (PUT → BD, mensaje "Reglas guardadas en la base de datos.") y "Guardar y sincronizar" (PUT → BD + POST `/vmalert/sync_rules` con polling de job, fase `reloading`). Estado visible en `#vmalert-rules-status`.

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
- **Servido verbatim (fix 500):** en `proxy_ui` estas consolas se sirven con la rama
  `elif admin_console: pass` (sin `_rewrite_base_href` ni `_filter_admin_tenants`): no tienen
  `datasource` (`ds`) asignado, y derivar el rewrite desde `ds` lanzaba
  `UnboundLocalError` → 500 en ambas consolas (spec 010 §9). Sus assets son relativos y
  resuelven bajo `/ui/{ticket}/`.
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

## 6d. Event loop y transacciones (anti-deadlock)

**Contexto (incidencia real):** el worker mantenía una transacción psycopg2 abierta durante
`await _run_ansible_vmalert` (playbook `install-binaries.yml`, minutos), `init_db()` (DDL de arranque
en el otro contenedor del gateway) quedaba encolado tras el primer lock y `_bootstrap_internal` —
corriendo síncrono en el event loop— congelaba uvicorn: el socket TCP aceptaba pero devolvía 0 bytes
(web colgada, `pg_stat_activity` con backends en `idle in transaction`/esperando lock).

Mitigaciones obligatorias:

- **Transacciones cortas (workers):** ninguna operación psycopg2 abierta cruza un `await` de I/O
  externa (Ansible, HTTP). Los processors se dividen en `*_load`/`*_persist` síncronos ejecutados con
  `asyncio.to_thread`: `vmalert_worker` (`_bootstrap_internal_sync`, `_deploy_load/_deploy_persist`,
  `_undeploy_load/_undeploy_persist`, `_reload_load`, `_sync_rules_load`, `_regen_scrapes_load`,
  `_allocate_vmalert_port`, `_get_*_url`, `_resolve_tenant_datasources`, `_enqueue_job`,
  `_update_progress_sync`) y `tenant_worker` (`_tenant_create_sync`, `_tenant_delete_sync`,
  `_parses_collect_users`, `_seed_*`, `_select_vmalert_node_auto`, `_update_progress_sync`).
- **Claim de jobs en hilo:** `base._process_pending_jobs` ejecuta
  `await asyncio.to_thread(self._claim_jobs)` (SELECT ... `FOR UPDATE SKIP LOCKED` + UPDATE, transacción
  corta con conexión propia); `_set_job_running/succeeded/failed` igual vía `to_thread`.
- **Endpoints async con DB:** todo `async def` que toca psycopg2 delega en `asyncio.to_thread`
  (`_parses_provision_catchup._collect_usernames`, `_enrich_and_persist_alerts` del webhook de
  Alertmanager —IA incluida, ya que `provider.generate` bloquea—, `_update_user_theme_sync`,
  `_proxy_prepare` del UI proxy, fase de autorización de `proxy_ui`). Los endpoints `def` ya corren en
  el threadpool de FastAPI. Barrido AST verificable: ninguna `async def` ejecuta `get_db_connection` /
  `cursor.execute` en su propio cuerpo (solo en helpers delegados).
- **Límites de espera (`database.get_db_connection`):** `connect_timeout=10` y
  `options="-c lock_timeout=15s"` en ambas rutas de conexión: un lock contendido falla en ≤15 s
  (`LockNotAvailable`, subclase de `OperationalError`) en lugar de esperar infinito.
- **`init_db` con advisory lock + retry:** `SELECT pg_advisory_lock(0x414E4F4D)` serializa el DDL de
  arranque entre los dos contenedores del gateway; ante `lock timeout`/`deadlock detected` reintenta
  5 veces con backoff (`attempt*2`); el DDL vive en `_init_db_ddl(conn, cursor, hash_password_func)`.
  Cualquier otro error conserva el comportamiento previo (`print` + return, no bloquea el arranque).
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
| Dual-mode drift | Flag explícito `vmalert_per_tenant` default false (P2), condicionales + detección por `vmalert_instances`, retrocompat. **Implementado:** `deploy-infra.yml` fuerza `true`; single solo se crea con flag `false` (§4.1/§4.8). |
| Deadlock Postgres → event loop congelado | Transacciones cortas + `lock_timeout=15s` + `connect_timeout=10` + advisory lock en `init_db` + todo psycopg2 en workers/endpoints async delegado a `asyncio.to_thread` (§6d). |
| Fuga tenant→instancia | Validación estricta en deps/proxy (nunca params cliente), scope ticket por tenant, middleware org_id_upper. |
| Alertmanager_global abuso | Requiere perfil `alerts_manager` (P5), TTL corto, rate-limit, audit, one-time ticket. |
| Pérdida estado jobs | `job_state` persistente en Postgres (P1-A), idempotency, timeout, recovery. |
| YAML retenido | Borrado en `deleted_cleanup` (P4-A), limpieza completa en hard-delete. |

