# Spec 012: vmalert Multi-tenant y Auto-provisioning

## 1. Objetivo
Habilitar instancias `vmalert` 1:1 por tenant con despliegue automático y selección de nodo de infraestructura.

## 2. Modelo de Datos

### 2.1 Tenants
Nuevos campos en `tenants`:
- `placement_mode`: `'manual' | 'auto'` — si `auto`, el worker elige nodo vmalert con menor carga
- `vmalert_node_id`: FK a `infrastructure_nodes` (component_type='vmalert')
- `vmalert_port`: puerto asignado del pool del nodo

### 2.2 Infrastructure Nodes
- `component_type = 'vmalert'` para nodos que hospedan vmalert
- `ports_pool`: JSONB array de puertos disponibles (ej: `[8880, 8881, ...]`)
- `tenants_count_active`: contador denormalizado
- `capacity_slots`: máximo tenants por nodo

### 2.3 Tenant Vmalert Instances
Tabla `tenant_vmalert_instances`:
- `tenant_id`, `instance_id` (FK infrastructure_nodes), `port`, `status`

## 3. Flujo de Alta de Tenant

1. `POST /api/v1/admin/tenants` con `placement_mode` y opcional `vmalert_node_id`
2. Se crea tenant con `status='provisioning'`
3. Se encola job `tenant_create` en `job_state`
4. **TenantWorker** procesa:
   - Auto-genera `account_id`/`project_id` (secuencias PG)
   - Seed `tenant_datasources` (idempotente, desde nodos select)
   - Si `placement_mode='auto'` y no hay `vmalert_node_id` → asigna nodo con menos carga
   - Encola `vmalert_deploy` si `has_alerts=true`
   - Encola `parses_provision`
   - Marca tenant `status='active'`

## 4. vmalert Deploy (VmalertWorker)

1. Asigna puerto del pool JSONB del nodo
2. Ejecuta `install-binaries.yml` con `vmalert_instances`:
   ```yaml
   vmalert_instances:
     - tenant_slug: "tenant-1"
       tenant_name: "Tenant 1"
       tenant_id: 1
       port: 8880
       rules_path: "/etc/anomalia/vmalert/tenant-1"
       alertmanager_url: "http://alertmanager-node:9093"
   ```
3. Ansible crea systemd unit `anomalia-vmalert-{slug}.service`
4. Registra en `tenant_vmalert_instances`, incrementa `tenants_count_active`

## 5. AI Chat con Restricción de Contexto

### 5.1 Endpoint
`POST /api/v1/ai/chat` — requiere JWT válido

### 5.2 Contextos (estrictos)
| Contexto | Acceso | Restricción |
|---|---|---|
| `vmalert_rules` | `tenant_id` + tenant access | Solo reglas vmalert/PromQL |
| `victoria_metrics_query` | user | Solo PromQL VictoriaMetrics |
| `victoria_logs_query` | user | Solo LogsQL VictoriaLogs |
| `victoria_traces_query` | user | Solo trazas VictoriaTraces |
| `pyroscope_query` | user | Solo profiling Pyroscope |
| `parses_query` | user | Solo dashboards Parses |

### 5.3 System Prompts
Cada contexto tiene system prompt estricto que:
- Define ámbito permitido
- Prohíbe responder fuera del ámbito
- Respuesta canónica si pregunta fuera de scope: "Solo puedo ayudarte con [tema]."

### 5.4 Frontend
- **vmalert rules modal**: Panel lateral con chat `vmalert_rules` (requiere tenant_id)
- **AI Assistant flotante**: Panel global con selector de contexto (metrics, logs, traces, profiling, dashboards, alerts)
- **Auto-context switch**: Cambia automáticamente al cambiar tab principal

## 6. Alertmanager Webhook

### 6.1 Endpoint
`POST /api/v1/webhook/alertmanager` — gated por `alerts_manager` + admin token

### 6.2 Procesamiento
1. Recibe payload Alertmanager estándar
2. Para cada alerta: enriquece con IA (`build_alert_prompt` + proveedor configurado)
3. Persiste en `alert_history` con `ai_analysis`
4. Respuesta con alertas procesadas y análisis

## 7. API Endpoints Nuevos

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/admin/infra/vmalert-nodes` | Nodos vmalert disponibles (capacidad, carga) |
| GET | `/api/v1/admin/alerts/tenants?mine=true` | Tenants filtrados por usuario actual |
| POST | `/api/v1/ai/chat` | Chat IA con contexto restringido |
| POST | `/api/v1/webhook/alertmanager` | Webhook Alertmanager con enriquecimiento IA |

## 8. Workers Background

### TenantWorker (30s interval)
- Procesa `tenant_create`, `tenant_delete`
- Auto-genera IDs, seed datasources, auto-placement, encola jobs dependientes

### VmalertWorker (30s interval)
- Procesa `vmalert_deploy`, `vmalert_undeploy`, `vmalert_redeploy`
- Asigna puertos, ejecuta Ansible, registra instancias

### Integración en FastAPI
```python
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    tenant_worker = TenantWorker(interval=30)
    vmalert_worker = VmalertWorker(interval=30)
    await tenant_worker.start()
    await vmalert_worker.start()
    yield
    await tenant_worker.stop()
    await vmalert_worker.stop()
```

## 9. Frontend

### 9.1 Tenant Modal
- Selector `placement_mode`: manual/auto
- Selector nodo vmalert (solo si manual) — carga de `/infra/vmalert-nodes`
- Auto-habilita/deshabilita según modo

### 9.2 vmalert Rules Modal
- Panel lateral AI Chat (`vmalert_rules` context)
- Requiere `tenant_id`, valida acceso via `verify_tenant_access`
- Solo responde sobre reglas vmalert/PromQL

### 9.3 AI Assistant Flotante (Global)
- Botón flotante fijo (bottom-right) visible para `alerts_manager`/`admin`
- Panel lateral con historial, input, selector de contexto
- Contextos: metrics, logs, traces, profiling, dashboards, alerts
- Auto-switch al cambiar tab principal (`tab-changed` event)
- Badge de tenant seleccionado

### 9.3 Auto-context Switch
- `tab-changed` event en `ui.switchTab()` → actualiza contexto AI
- `tenant-selected` event → actualiza badge de tenant

## 10. Ansible Integration

### install-binaries.yml
- Recibe `vmalert_instances` como extra_vars
- Role `vmalert` en modo dual (por tenant + single) ya implementado
- Crea systemd units `anomalia-vmalert-{slug}.service`

### Vmalert Service Template
```ini
[Service]
ExecStart=/usr/local/bin/vmalert
  --datasource.url=http://vmselect:8401
  --remoteRead.url=http://vmselect:8401
  --remoteWrite.url=http://vminsert:8400
  -notifier.url=http://alertmanager:9093
  -rule=/etc/anomalia/vmalert/{tenant_slug}/alert_rules.yml
  --httpListenAddr=:{port}
```

## 11. Base de Datos - Secuencias

```sql
CREATE SEQUENCE IF NOT EXISTS tenant_account_id_seq START 1000;
CREATE SEQUENCE IF NOT EXISTS tenant_project_id_seq START 1000;
```

## 12. Testing

### Endpoints a probar
1. `POST /api/v1/admin/tenants` con `placement_mode=auto`, `has_alerts=true`
   - Verificar: tenant `status=active`, `account_id`/`project_id` asignados, `vmalert_node_id` asignado
   - Verificar: job `vmalert_deploy` ejecutado, systemd unit running
   - Verificar: `tenant_datasources` poblado

2. `POST /api/v1/ai/chat` con `context=vmalert_rules`, `tenant_id=X`
   - Verificar: respuesta solo sobre PromQL/vmalert
   - Verificar: 403 si usuario sin acceso al tenant

3. `POST /api/v1/ai/chat` con `context=victoria_metrics_query`
   - Verificar: respuesta solo PromQL
   - Verificar: rechazo preguntas fuera de scope

4. `POST /api/v1/webhook/alertmanager` con payload estándar
   - Verificar: `alert_history` poblado con `ai_analysis`

5. Frontend: AI Assistant flotante
   - Toggle abre/cierra panel
   - Cambio de tab principal → auto-switch contexto
   - Selector de contexto funcional
   - Mensajes user/assistant renderizados correctamente
