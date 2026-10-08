# Spec 008 — Parses: Datasources por defecto y scoping por roles/perfiles/tenants

## 1. Objetivo

Que Perses abra con los datasources y dashboards que Anomalia define (uno por tenant) y
que el acceso a los datos de cada tenant dependa de los roles, perfiles y tenants del
usuario, sin poder leer telemetría de un tenant ajeno.

Decisiones aprobadas por el usuario en 2026-09-29:

1. **Aislamiento de red**: regla de firewall que restringe los puertos de **lectura** de
   Victoria a solo el puente docker y localhost (VIP para el puente, no loopback porque
   los consumidores —backend y parses— viven en contenedores).
2. **Provisioning por usuario al iniciar sesión**: el backend crea/actualiza en Perses un
   project + datasources + dashboard por usuario, con la URL del proxy y un **token
   firmado de vida corta** con alcance limitado a los tenants del usuario.

## 2. Topología de lectura (verificada empíricamente)

Se sondeó cada backend en vivo. Resultado:

| Tenant | Backend | URL de lectura | scoping | Plugin Perses |
|---|---|---|---|---|
| METRICS (1) | vmselect `8401` | `/select/0:0/prometheus/api/v1/*` | **prefijo de path** `0:0` | `PrometheusDatasource` ✅ |
| AUDIT_LOGS (4) | vlselect `8481` | `/select/logsql/*` | **headers** `AccountID`/`ProjectID` (`0`/`3`) | `VictoriaLogsDatasource` ✅ |
| PROFILES (3) | pyroscope `4040` | `/pyroscope/render` | **header** `X-Scope-OrgID: PROFILES` | `PyroscopeDatasource` ✅ |
| TRACES (2) | vtselect `8491` | `/select/jaeger/api/*` | **headers** `AccountID`/`ProjectID` (`0`/`1`) | `JaegerDatasource` ✅ |

Formato de URL confirmado contra el binario (`vmselect-...-v1.153.0-cluster`):
`/select/<accountID>:<projectID>/prometheus/...` — dos puntos, no barra. `vminsert` (8400)
es ingest puro y no responde queries.

**Correcciones a la v1 de esta spec:**

- **TRACES SÍ es viable**: la primera versión afirmaba que Perses no tenía plugin Jaeger.
  Es falso: el build desplegado registra `JaegerDatasource` + `JaegerTraceQuery`, y
  VictoriaTraces v0.12.0 expone la API de lectura con formato compatible con Jaeger
  (`/select/jaeger/api/services` responde, `/api/v2/...` de Tempo **no** se enruta). Por
  eso **no** se usa `TempoDatasource` y sí `JaegerDatasource`.
- **`kind` de la tabla `tenant_datasources` identifica el backend de almacenamiento**
  (VictoriaMetrics, VictoriaLogs, VictoriaTraces, Pyroscope), no el formato de la API.
  No existe ningún componente Jaeger en el stack.

## 3. Restricciones de Perses (investigadas en el build desplegado)

El build es `persesdev/perses@sha256:b6d075c2...` (2026-09-22, rev 3b2461b5). La API
cambió respecto a la documentación estable, así que la spec ancla el shape verificado:

1. **API REST en `/api/v1`** (sin OpenAPI). Recursos verificados:
   - `POST /api/v1/projects` con `{"kind":"project","metadata":{"name":...}}`.
   - `POST/GET/DELETE /api/v1/datasources` — son de **ámbito project**: obligan
     `metadata.project`.
   - Datasource proyect: `{"kind":"Datasource","metadata":{name,project},"spec":{
     "default":false,"plugin":{"kind":"<Plugin>Datasource","spec":{"proxy":{
     "kind":"HTTPProxy","spec":{"url":...,"headers":{...}}}}}}}`.
   - El proxy de datasource es del **servidor** de Perses: `GET /proxy/projects/<p>/datasources/<n>/<path>`
     consulta a Victoria con los headers del datasource y devuelve datos reales.
   - `allowed_endpoints` **no existe** en este build (rechazado por schema).
   - Kubernetes discovery a un lado: el proxy HTTP es suficiente.
2. **HTTPProxy soporta `headers`** (verificado: se guarda y aplica). Es el canal para
   inyectar el token por usuario sin exponerlo al navegador: el navegador habla con
   Perses server, y Perses server es quien agrega el header al ir al backend.
3. **No reenvía el JWT del usuario** (perses/perses#2942): Perses firma su propio token y
   el original se pierde. Ningún scoping de UI protege los datos.
4. Storage es **basado en archivos** (`database.file.folder: /perses`, JSON) pero
   **también** hay REST API de escritura (los POST funcionaron). El provisioning
   declarativo re-inyecta cada `1h` (`provisioning.interval`).
5. Perses actualmente corre `enable_auth: false` y expone `8090` en la LAN sin auth.
6. **`spec.default` es lo que resuelve las variables** (verificado en el bundle del
   build desplegado). Las `ListVariable` no llevan `datasource` propio: el plugin
   (p. ej. `PrometheusLabelValuesVariable`) resuelve `e.datasource ?? {kind:
   "<Plugin>Datasource"}` — o sea, **el datasource de ese plugin con `default:
   true`**. Si ningún datasource lo tiene, la resolución devuelve sin cliente, el
   plugin devuelve `[]` **sin emitir ninguna petición HTTP** y la variable queda
   vacía (`job=~""` → todos los paneles en "No data"). Por eso
   `_datasource_payload(..., is_default=True)` marca con `default: true` **solo al
   primer datasource de cada tipo de plugin** (mismo criterio que
   `datasources_by_kind`); los demás quedan en `false`.

## 4. Corrección de diseño: las lecturas NO pasan por vmauth

La primera versión enroutaba lecturas por vmauth. Es incorrecto: vmauth solo expone
`unauthorized_user`, y como Perses no reenvía su token, la única autorización posible
ahí es "sin autorización". Enrutar por vmauth daría **cero aislamiento** mientras
aparentaría seguridad.

Por eso el backend es el **gateway de lectura** (coherente con spec 007): valida con
`verify_tenant_access` y habla directo con el nodo *select*. vmauth queda como router de
**ingesta**, que no necesita identidad de usuario.

## 5. Aislamiento de red (decisión 1)

Los componentes Victoria son **servicios systemd** en el host que hacen bind a
`{{ ip }}` (`ansible_host` = IP LAN) `:{{ port }}`. Consecuencia verificada: `8401`,
`8481`, `8491` y `4040` estaban abiertos en la LAN **sin autenticación**; cualquiera
pisaba el frontend y consultaba los cuatro tenants. Solo enlazar a `127.0.0.1` no sirve:
backend y parses viven en contenedores y entran por el puente docker, no por loopback.

Diseño (implementado como role `victoria_firewall`, doble backend auto-detectado —
ver `specs/009-platform-support-and-prerequisites.md`):

- **Backend firewalld** (RHEL-family, firewalld activo): rich rules nativas por puerto
  (`accept` desde cada fuente en `victoria_firewall_allowed_sources` + `drop` para el
  resto), aplicadas con `firewall-cmd` (`--query-rich-rule` / `--add-rich-rule` /
  `--reload`, idempotente) usando solo módulos `ansible.builtin`. Sobre viven recargas
  de firewalld y es la vía soportada por Red Hat.
- **Backend iptables** (Debian/Ubuntu u host sin firewalld): cadena dedicada
  `ANOMALIA_VICTORIA_READ` (`iptables`/`nf_tables`), unit systemd
  `anomalia-victoria-firewall.service` que re-aplica el script
  `/etc/anomalia/firewall/apply-victoria-firewall.sh`. La unit depende del motor de
  contenedores activo (`{{ anomalia_engine_service }}`).
- Reglas INPUT para los puertos de lectura **de un conmutador (switch)**, nunca política
  global (conjunto `victoria_firewall_ports`):
  1. ACCEPT desde cada CIDR de `victoria_firewall_allowed_sources` (puente de
     contenedores `172.16.0.0/12` por defecto — detectado real `172.18.0.0/16` —, loopback
     y la IP LAN del propio host para vmagent/vmalert).
  2. DROP para cualquier otro origen.
- Ambos backends comparten `victoria_firewall_enabled` (toggle `false` en clouds donde el
  security group ya aísla) y `victoria_firewall_allowed_sources` (lista de CIDRs
  parametrizable para despliegues públicos; ver spec 009 §Despliegue público).
- Para publicarlo: no exponer los puertos de lectura; aceptar solo la subred **exacta** del
  puente (`docker network inspect anomalia_aiops-net`) y los CIDRs de administración/VPN.
- Fuera de alcance de esta regla: puertos de **inscripción/almacenamiento** (8400, 8480,
  8490, 8402, 8482, 8492). Se documentan como exposición residual a revisar.

## 6. F1 — Tabla `tenant_datasources`

`tenants.port` guarda el puerto de **inserción** y no permite derivar la URL de lectura.
Tabla nueva (implementada en `backend/app/database.py` y `init.sql.j2`):

| Columna | Tipo | Notas |
|---|---|---|
| `tenant_id` | INT FK → `tenants(id)` | PK, 1:1 |
| `kind` | VARCHAR | backend de almacenamiento: `VictoriaMetrics` \| `VictoriaLogs` \| `VictoriaTraces` \| `Pyroscope` |
| `read_url` | TEXT | URL base del backend de lectura (resuelta del inventario en el seed) |
| `scoping` | VARCHAR | `path` \| `header` — cómo se aísla |
| `account_id` / `project_id` | INT NULL | para `path` → `/select/{a}:{p}/prometheus`; para `header` → values `AccountID`/`ProjectID` |
| `org_id` | TEXT NULL | `X-Scope-OrgID` (solo `profiles`) |
| `enabled` | BOOLEAN | apaga un datasource sin borrarlo |

Seed idempotente con `ON CONFLICT (tenant_id) DO UPDATE`, parametrizado con las IPs/ports
de los nodos *select* del inventario (no hardcodeadas).

## 7. F3 — Proxy de lectura y token (decisión 2)

```
Navegador → Perses server (/proxy/projects/<p>/datasources/<n>/...) 
          → gateway TLS  https://anomalia_gw_tls:8443/api/v1/parses/datasources/{tenant_id}/{ruta}
                                  (header X-Anomalia-Token: Bearer <token>, TLS validado contra la CA del Secret)
          → verify_tenant_access → nodo *select* Victoria (scoping de la BD)
```

> **El proxy apunta al gateway por HTTPS, no por el puerto claro** (verificado
> empíricamente): `anomalia_gw` corre con `FORCE_HTTPS=true`, así que su
> middleware `enforce_https_redirect` devuelve `301` al pedirle el datasource por
> `http://anomalia_gw:8000`. El proxy HTTP de Perses no puede seguir ese redirect
> contra un puerto HTTP plano y las consultas fallaban; por `https` la misma
> ruta responde `401` normal, o sea que el problema era exclusivamente la
> redirección, no RBAC ni firewall.

> **El token viaja en `X-Anomalia-Token`, no en `Authorization`** (verificado
> empíricamente): el `HTTPProxy` de Perses reenvía headers custom pero **filtra**
> `Authorization`, así que un token en ese header llegaba al gateway como 401
> "Token de proxy de Parses ausente".

- **Confianza TLS**: Perses valida el certificado del gateway contra el ancla del
  `Secret` de proyecto `anomalia-proxy-ca`, referenciado en `proxy.spec.secret`.
  Perses **exige `Secret` y no acepta `GlobalSecret`** en los datasources de
  proyecto. El backend lee el PEM de `PARSES_TLS_CA_FILE`
  (`/certs/ca.crt`, montado en solo lectura desde `/opt/anomalia/certs`) y
  garantiza el `Secret` por proyecto con `spec.tlsConfig.ca` antes de escribir
  los datasources (`_ensure_proxy_ca_secret`). Si el PEM no está disponible se
  omite el `Secret` y el proxy queda en `http`, que es el modo de desarrollo sin
  certificados (`tls_enabled=false`, donde tampoco existe `anomaliagw_tls`).
- El proxy resuelve la fila de `tenant_datasources`, valida acceso
  (`user_tenants ∪ role_tenants`, no claims), inyecta el scoping según la fila y reenvía.
  El tenant viene del path; los valores de aislamiento y la URL salen de la BD, nunca del
  request. Métodos solo `GET`/`POST`; rechazo de `..` y de rutas con `://`.
- `GET /api/v1/parses/datasources` devuelve los datasources del usuario (contraparte de
  `/tenants/my-tenants`).
- **Token de proxy** (`PARSES_PROXY_TOKEN_TTL`, default **86400 s = 24 h**): JWT HS256
  firmado con la misma `SECRET_KEY`, claims `sub`=username, `tenants`=[ids],
  `purpose`="parses-proxy". El router valida `purpose` y `verify_tenant_access`
  re-chequea la BD. Se re-emite en cada login; un token expirado solo rompe el
  dashboard hasta el próximo login. El valor va en `docker-compose.yml.j2` en
  **los dos** servicios del gateway, con comentario que remite a esta spec.
- **Catch-up de provisioning al arranque del gateway** (spec 008 / spec 013): tras un
  destroy+deploy los datos de Perses (`database.file.folder: /perses`, sin volumen
  persistente) se pierden. El backend ejecuta en `lifespan` un catch-up **no bloqueante**
  (`asyncio.create_task(_parses_provision_catchup)`) que re-provisiona el project,
  datasources y dashboards para **todos los usuarios activos**. Idempotente
  (GET→POST/PUT) y tolerante a que Parses aún no esté listo: `provision_user_parses`
  reintenta transitorios con backoff y el próximo login cubre el residuo. El rol `parses`
  se despliega **antes** que `backend` y espera readiness del puerto (`wait_for`).
- **Provisioning por usuario al login** (non-blocking, `BackgroundTasks`): el backend
  llama a la REST de Perses y garantiza que existan:
  1. Project `anomalia-<hash de username>`.
  2. El `Secret` de proyecto con la CA del proxy (ver "Confianza TLS" arriba).
  3. Un `Datasource` por tenant al que el usuario tiene acceso, con
     `proxy.url = https://anomalia_gw_tls:8443/api/v1/parses/datasources/{tenant_id}` y
     `proxy.headers["X-Anomalia-Token"] = Bearer <token>`. El **primero de cada tipo
     de plugin** lleva además `spec.default = true`, que es el que resuelve las
     variables `ListVariable` y las queries sin selector explícito (ver §3.6).
      Los backends con scoping por header exponen su API bajo un prefijo de ruta que se
      **embebe en la URL del proxy** (`HEADER_UPSTREAM_PREFIX_BY_STORAGE`), porque los
      plugins de Perses llaman en la raíz pero el clúster Victoria responde bajo prefijo
      (verificado contra los upstreams reales y contra los chunks del build desplegado):

      | Backend | Prefijo embebido | Plugin pide |
      |---|---|---|
      | VictoriaTraces | `/select/jaeger` | `/api/services`, `/api/traces` (raíz) |
      | VictoriaLogs | `""` | `/select/logsql/query` (ya lo trae) |
      | Pyroscope | `""` | `/querier.v1.QuerierService/…` (raíz) |

      Embeber un prefijo que el plugin ya trae produce una ruta doble que el upstream
      rechaza con `400 unsupported path requested: "/select/logsql/select/logsql/query"`;
      omitir el que falta produce `404`. El prefijo `"/pyroscope"` que se probó primero
      **no sirve**: el build desplegado solo llama a `querier.v1.*`, que responde en la
      raíz y devuelve `404` bajo `/pyroscope/` (el `/pyroscope/render` legado sí existe
      pero el plugin no lo usa).

      Ejemplo efectivo: el plugin Jaeger pide `/api/services` → la URL del proxy ya trae
      `/select/jaeger`, así que el gateway recibe `/select/jaeger/api/services` y su
      allowlist lo acepta sin reescribir nada.
  4. Los dashboards del tenant METRICS migrados desde Grafana y ligados a su
     datasource (ver § 8), y el dashboard nativo de la plataforma (ver § 9).
  Idempotente: `GET` existente → `PUT`/update, ausente → `POST`.
- **La rotación de la CA exige redeploy**: `certs_force=true` genera un `ca.crt`
  nuevo y el `Secret` solo se refresca en el siguiente login de cada usuario. El
  material TLS lo produce el role `certs` (spec 007 §2.3).
- **Timestamps Jaeger: sin conversión** (antes había `_jaeger_ns_params`):
  VictoriaTraces implementa la API HTTP de Jaeger y espera `start`/`end` en
  **microsegundos**, igual que el estándar de Jaeger y que lo que emite el plugin
  Jaeger de Perses (`1e3 * Date.getTime()`). La conversión ×1000 a nanosegundos que
  existió en el proxy **rompía la búsqueda de trazas**; medido contra
  `/select/jaeger/api/traces?service=anomalia_system&limit=5` con el mismo rango
  (1 h y 24 h) sobre vtselect v0.12.0:

  | Unidad enviada | Resultado |
  |---|---|
  | microsegundos | `200` en **8 ms**, 43 KB, 5 trazas |
  | nanosegundos | `200` en **30 000 ms** (= `UPSTREAM_TIMEOUT_SECONDS`), `total: 0` |
  | segundos | `400 request time out of retention` |

  En el proxy los params se reenvían **tal cual** (`request.query_params`), para
  todos los tenants. Solo cambia el comportamiento de `api/traces` (búsqueda) y
  `api/dependencies`, que son los únicos con params temporales: `api/services`,
  `api/traces/{id}` y `api/operations` (sintetizado en § 7) no llevan `start`/`end`,
  así que nada de lo que funcionaba dependía de la conversión.

## 8. F2 — Dashboards del tenant METRICS (migración Grafana → Perses)

Los dashboards se **migran** con el endpoint nativo del servidor de Perses
(`POST /api/migrate`, que cuelga de `/api`, NO de `/api/v1`) en lugar de escribirse a
mano. Fuente: JSON de dashboards de Grafana en `backend/dashboards/grafana/metrics/`
(los copia el role de backend a `/opt/anomalia/backend` sin cambios en Ansible).

Flujo en `provision_user_parses` (login, background task), por cada tenant `metrics`:

1. `sanitize_grafana_dashboard()` — el migrador es **atómico**: un panel no soportado
   tumba el dashboard entero. Se sanea el JSON antes de enviarlo:
   - `table` + `fieldConfig.defaults.thresholds` → se descarta el umbral (el panel
     Table de Perses no tiene equivalente numérico; falla con
     `_thresholdNumericSteps: undefined field: value`).
   - `fieldConfig.overrides[].properties` con `id` repetido → se conserva el primero
     (Perses modela un `querySettings` por query, no por serie, así que dos
     `custom.lineStyle` colisionan con `conflicting values "dashed" and "solid"`).
   El recorrido de paneles es **recursivo**: Grafana anida paneles en filas colapsadas.
2. `migrate_grafana()` — `POST /api/migrate` con `{"grafanaDashboard": {...}}`. El
   resultado se cachea en `backend/dashboards/migrated/<sha256>.<versión>.json`; la
   traducción no depende del usuario ni del proyecto, así que se calcula una vez por
   dashboard (clave versionada para invalidar la cache si cambian las reglas).
3. Control de calidad — si **todas** las queries del dashboard migrate a
   `migration_from_grafana_not_supported` (datasource de Grafana sin equivalente en
   Perses), el dashboard **no se despliega** y se avisa por log. Si solo algunas, se
   despliega y se avisa cuántas quedaron sin datos.
4. `bind_metrics_datasource()` — el migrador deja la variable de datasource como
   `DatasourceVariable` (dropdown vacío). Se reemplaza por una `StaticListVariable`
   con un único valor (`ds-metrics`), de modo que todas las queries que referencian
   `$ds` / `${ds}` / `$DS_PROMETHEUS` resuelven al datasource del tenant. De paso se
   ocultan las variables que el migrador no traduce (adhoc filters, que quedan con los
   valores `grafana/migration/not/supported`).
5. `_normalize_list_variable_defaults()` — Perses representa la opción "All" con la
   cadena **`$__all`** (el dropdown la inyecta como `{value:"$__all"}` y el store la
   detecta con `"$__all" === value`). El migrador deja las variables en dos estados
   que impiden arrancar con todas las opciones:
   - `defaultValue: ["$__all"]` (la lista heredada de `current.value` de Grafana):
     no coincide con la opción "All" y se usa **literalmente**, o sea
     `job=~"$__all"` → sin coincidencias;
   - sin `defaultValue`: Perses selecciona la **primera** opción, así que los paneles
     quedan filtrados a un único `job`/`instance`.

   La función normaliza el primer caso a la cadena y rellena el segundo con
   `"$__all"` cuando `allowAllValue` es `true`. No toca escalares (`v0.1.0`, `5`)
   ni `StaticListVariable`/`DatasourceVariable` (el `ds` del paso 4 debe conservar su
   valor concreto). Se aplica sobre el documento **después** de leerlo de la caché, así
   que no hace falta versionar `_SANITIZER_VERSION`.
6. `_ensure_dashboard()` — `GET` → `PUT`, ausente → `POST` (409 → `PUT`).
   `metadata.project` = project del usuario; `metadata.name` =
   `<slug-archivo>--<datasource>` (p. ej. `vmauth--ds-metrics`) para que un usuario
   con varios tenants METRICS tenga un juego por tenant sin colisiones.

**Resultado verificado** sobre los dashboards entregados: 6 de 7 desplegados, todos con
todas las queries ligadas a `ds-metrics` y respondiendo con datos reales de
VictoriaMetrics (`vl_*`, `vt_*`, `vmauth_*`, `vmagent_*`). Paneles por dashboard:
`victoria_metrics_cluster` 99, `victoria_traces_cluster` 88, `victorialogs_cluster` 87,
`vmagent` 81, `vmalert` 41, `vmauth` 27 (423 en total).
`victoriametrics_anomaly.json` queda fuera: sus 17 queries dependen del plugin
VictoriaMetrics Anomaly de Grafana (no son PromQL) y Perses no tiene equivalente.
`victoria_traces_cluster.json` despliega con 3 de 116 queries como placeholder.

**Degradaciones aceptadas** (documentadas, no bloquean): umbrales numéricos en tablas
y estilos de línea por serie no sobreviven la migración; los paneles siguen mostrando
datos y formato.

## 9. F2.1 — Dashboard nativo de la plataforma (`anomalia-stack`)

Además de los dashboards migrados (que cubren el **estado de la infraestructura**), se
despliega un dashboard propio de la plataforma que muestra la **telemetría del propio
backend Anomalia**:

| Panel | Plugin Perses | Datasource | Datos |
|---|---|---|---|
| `CPU %` / `RAM %` / `Health` | `StatChart` | Prometheus | `anomalia_system_cpu_usage_percent`, `anomalia_system_ram_usage_percent`, `anomalia_health_status` (métricas del endpoint `/metrics`, job `anomalia-backend`) |
| `CPU / RAM del backend` | `TimeSeriesChart` | Prometheus | las dos series anteriores sobre 1h |
| `Trazas del backend` | `TraceTable` | Jaeger | `service=anomalia_system` (las trazas OTLP que el backend envía a VictoriaTraces). El nombre de cada fila es un enlace que rellena la variable `trace_id` |
| `Traza seleccionada` | `TracingGanttChart` | Jaeger | `traceId=$trace_id` (vacío al arrancar, luego la traza elegida) + `service=anomalia_system` |
| `Perfil de CPU` | `FlameChart` | Pyroscope | `service=anomalia_system` + `profileType=process_cpu:cpu:nanoseconds:cpu:nanoseconds` (perfilado continuo; el id tiene 5 campos separados por `:` y no es el literal `cpu` — el plugin deriva la unidad del tercero) + `traceHeight: 16` con `layouts` `height: 16` (altura por nivel y viewport ampliado; ver el bloque de `traceHeight` más abajo) |
| `Perfil de memoria` | `FlameChart` | Pyroscope | `service=anomalia_system` + `profileType=memory:alloc_space:bytes:space:bytes`. Panel gemelo del de CPU (layout `x=12, width=12`, misma fila `y=20`): como el plugin no admite selector de perfil en cabecera (ver bloque siguiente), el dashboard expone los dos perfiles lado a lado |

**Plantilla:** `backend/dashboards/native/anomalia_stack.json`, un dashboard Perses
normal con una peculiaridad: cada query declara el tipo de datasource que necesita con
el marcador `xAnomaliaDatasource: "<pluginKind>"`. `provision_native_dashboards()`
resuelve el marcador contra los datasources del usuario:
`{"kind": "<pluginKind>", "name": "<datasource real>"}`. Si el usuario **no tiene** un
tenant de ese tipo, el panel se **descarta** (mejor un dashboard con menos secciones que
un panel roto); si no queda ningún panel, el dashboard no se despliega. Para el admin
(4 tenants) se despliegan los 7 paneles.

**Verificación end-to-end** (gateway de prueba, `gw_test`): validación de schema del
dashboard completo contra el Perses real, selectores resueltos a los datasources del
usuario, y data real por proxy para las tres rutas:
`/api/v1/query` (métricas → `anomalia_system_ram_usage_percent` = 74.7),
`/api/traces`+`/api/services` (traza `GET /metrics`, SDK OTel python 1.45.0) y
`/render` (perfil `process_cpu`, ticks > 0 en ventana 1h).

**Fixes de bindings entre plugins de Perses y el clúster Victoria** (verificados
empíricamente, no suposiciones):
- Plugin Jaeger de Perses llama `/api/services`, `/api/operations`, `/api/traces`,
  `/api/traces/{id}`; el clúster Victoria solo responde bajo `/select/jaeger/...`
  (con headers `AccountID`/`ProjectID`). → prefijo embebido en `proxy.url` (ver § 7).
- Plugin Pyroscope de Perses (0.7.0-beta.6) llama por **POST** a
  `/querier.v1.QuerierService/{ProfileTypes,SelectSeries,SelectMergeStacktraces,LabelNames,LabelValues}`
  (los cinco endpoints que su propio editor lista como `allowedEndpoints`); el
  selector de labels se construye en el cliente como `service` + `filters` →
  `{service_name="x"}` y `start`/`end` viajan en **milisegundos** (el código
  comenta *"Pyroscope's Connect API expects timestamps in milliseconds"*). El
  destino es el servidor Pyroscope real (`tenant_datasources.read_url = :4040`,
  cabecera `X-Scope-OrgID`), no el `/pyroscope/` de vmselect. **La doc de Perses
  está desactualizada aquí**: `docs/pyroscope/model.md` sigue documentando
  `query: '{...}'` y endpoints `/render`, `/labels`, `/label-values` (GET), pero el
  schema cue `close()` solo admite `profileType`, `service`, `filters`, `maxNodes` y
  `datasource`, y `createInitialOptions()` no siquiera genera un campo `query`.
- Los timestamps Jaeger (`start`/`end`) viajan en **microsegundos**, sin conversión
  en el proxy: nanosegundos cuelga 30 s y devuelve `total: 0`, segundos da
  `request time out of retention` (§ 7).

**`service` es obligatorio en `PyroscopeProfileQuery`** (leído en el código que trae el
plugin 0.7.0-beta.6, `lib/model/profile-query-model.js`):
`isProfileQueryComplete(spec) { return !!spec.service && !!spec.profileType; }`. Si falta
`service` **no hay error en consola**: `getProfileData` devuelve `emptyProfileData()`
(`timeline: {startTime: 0, samples: [], durationDelta: 0}`), el FlameChart calcula
`min = max = 0` y dibuja una rejilla vacía con el eje en **1970**. Con `service`, el
cliente arma `{service_name="anomalia_system"}` y la cadena Perses → gateway → Pyroscope
devuelve 200 con el flamegraph completo. El selector se construye en el propio plugin a
partir de `service` + `filters`: **no existe un campo `query`** (ver la advertencia sobre
la doc oficial arriba).

**`traceHeight` evita el flamegraph ilegible en perfiles profundos** (leído en
`FlameChartPanel.js` y `FlameChart.js` del plugin 0.7.0-beta.6; evidencia de la
captura del 2026-10-02 21:39): con `service` el perfil `process_cpu` de
`anomalia_system` devuelve **204 niveles** (`SelectMergeStacktraces` →
`flamegraph.levels`, 653 nombres), y sin `traceHeight` el panel usa
`tableFlameChartHeight = contentDimensions.height` (~410 px con `layouts height: 10`)
y dibuja con `yAxisMax = maxDepth` → **~1,6 px por nivel**: los rectángulos quedan
sub-píxel, solo se imprimen las etiquetas de los frames ≥ 1 % (`total`, `<module>`,
`__call__`, `main`, `invoke`…) y todas se solapan en una banda ilegible de ~25 px en
la parte alta, con el resto en blanco. El remedio es del propio plugin:
`flame.cue` admite `traceHeight?: int & >=0` y `FlameChartPanel` calcula
`tableFlameChartHeight = max(available, maxDepth * traceHeight)` sobre un `Stack` con
`overflowY: auto` (scroll interno del panel; el propio código lleva
`// TODO (gladorme): allow users to override height (useful for explorer for stack
traces with high depth)`). La plantilla lleva `traceHeight: 16` (204 × 16 ≈ 3264 px,
fila ≈ 15,6 px) y `layouts` con `height: 16` (~650 px > 600, el umbral de
`LARGE_PANEL_THRESHOLD` que activa `reservedHeight` y amplía la zona visible de
tabla/flame a ~380 px). `traceHeight` solo se edita en *Editar panel* (la barra de
settings in-panel solo trae paleta y Table/Flame Graph/Both); al hacer *Focus block*
(zoom) `maxDepth` baja y el área se acorta sola. La suite offline (v8) comprueba que
las claves del plugin son exactamente las del `close()` de `flame.cue` y que
`traceHeight > 0`. `Self: 0.00ns` en las filas intermedias de la tabla es correcto:
`self` real solo existe en hojas (el tooltip de una hoja muestra el valor, p. ej.
`Self: 3s480ms`).

**Vinculación tabla de trazas → Gantt** (los tres elementos van en la plantilla):
- `spec.variables`: una `TextVariable` `trace_id` con `value: ""` y etiqueta visible;
  Perses la pinta como input en la cabecera del dashboard.
- Panel `2_0` (`TraceTable`): `spec.links.trace: "?var-trace_id=${traceId}"`.
  `replaceVariablesInString` sustituye `${traceId}` por el id de la fila y el `Link` del
  nombre navega con un `to` **relativo** (empieza por `?`), de modo que conserva el
  prefijo `/ui/{ticket}/`.
- Panel `2_1` (`TracingGanttChart`): `traceId: "$trace_id"`. Con la variable vacía el
  plugin sigue en la ruta de búsqueda y muestra su aviso de *"please enter a trace id"*
  (con `service` presente no lanza); al rellenarse llama a `/api/traces/{id}` y pinta el
  Gantt.
- Efecto lateral aceptado: al navegar con `?var-...` se sustituye la query string
  completa, así que se pierden los params `start`/`end` y el rango temporal vuelve al
  valor por defecto del dashboard.
- Validación real sin tocar el despliegue: `POST /api/validate/dashboards` con el
  dashboard **ya resuelto** (marcadores sustituidos) devuelve **200**; la suite offline
  (`test_parses_ui.py`, v8) comprueba los mismos invariantes sin red.

**Errores de consola benignos (2026-10-02)** — no salen de este proxy:
- `404 {"message":"document not found"}` para `roles`, `rolebindings` y
  `ephemeraldashboards` los devuelve el **propio origen de Perses**
  (`http://<host>:8090/api/v1/projects/<proyecto>/...`); `_parses_guard_path` los deja
  pasar por ser rutas del proyecto propio y la UI los tolera.
- Los avisos de federación de React (host 18.3.1 vs peers 18.2.0) son ruido de versión
  compartida: los módulos cargan igual.
- `Cannot read properties of null (reading 'offsetWidth')` en ECharts
  (`manuallyShowTip → _showAxisTooltip → _showOrMove → _updatePosition → getSize`) es
  una **carrera upstream benigna**: el tooltip se encola en `setTimeout(showDelay)` y el
  gráfico se desmonta antes de resolverse (hipótesis: pulsar *Table/Flame Graph/Both*,
  que desmonta un gráfico mientras su tooltip sigue encolado). **No es** —como decía
  esta línea— síntoma de `min = max = 0`: se reproduce el 2026-10-02 con el flamegraph
  ya pintado y `service` presente (2 ocurrencias en la sesión de las 21:39). Solo
  ensucia la consola, no rompe la UI y **no tiene arreglo desde el JSON del dashboard**;
  verificar tras cada despliegue si persiste y en qué interacción.

**`spec.layouts` es obligatorio** (verificado en el build desplegado): la plantilla no
lo traía y Perses lo guardaba como `layouts: null`. Al renderizar, el bundle
desestructura `layouts: D = []` —el default de JS **no** aplica a `null`— y lo pasa a
`function C(e){ … for(const r of e){…} }`, que levanta
`TypeError: e is not iterable` y deja el dashboard sin abrir (por eso `anomalia-stack`
no cargaba). La plantilla lleva un `Grid` con un `item` por panel
(`content: {"$ref": "#/spec/panels/<clave>"}`, 24 columnas, sin solapes) y la suite
offline comprueba que los 7 paneles quedan referenciados.

**Degradación por diseño**: los paneles de trazas/perfilado del inquilino dependen de
que el tenant TRACES/PROFILES esté asignado al usuario; si no, `anomalia-stack` pierde
esas secciones sin errores.

**Edición desde la UI — *Edit → Query con preview en vivo → Save* (verificado
empíricamente 2026-10-03, Chrome headless contra el despliegue real).** Este es el
flujo "Aceptar/Aplicar" de la consola; el botón que persiste es **Save**:

- Toolbar **Edit** → en modo edición el botón `show panel actions for <panel>` de la
  cabecera está visible (en modo vista el contenedor depende de la variable CSS
  `--panel-hover`, que el `<section data-testid="panel">` solo activa con `:hover`) →
  `edit panel <nombre>` → drawer `Edit Panel (ID: <clave>)` con **Apply**/**Cancel**.
- **Las pestañas del editor (`Query`, `Settings`, `Links`, `JSON`, `Layout`) tardan
  ~10-15 s en aparecer**: `PanelSpecEditor` hace `if (isLoading) return null` mientras
  resuelve el plugin de panel vía module federation (los chunks del plugin se piden al
  abrir el drawer). Hasta que no hay pestañas no existe el campo *Profile Type*; el
  bloque **Preview** (siempre visible, `h4`) sí se monta antes.
- El Preview envuelve `DataQueriesProvider` **sin** `queryOptions.enabled`, así que sus
  queries se disparan solas: al abrir el editor del panel `3_0` salen `ProfileTypes` y
  `SelectMergeStacktraces` (200) y el flamegraph se pinta con datos reales. En cambio,
  en modo vista cada panel envuelve sus queries en `queryOptions: {enabled: inView}`
  (IntersectionObserver del `<section>`): un panel que no ha entrado en el viewport
  muestra la caja vacía sin disparar nada.
- Pestaña **Query** → `QUERY #1`: *Profile Type* es un `Select` nativo de MUI (label
  `Profile Type`, `role="combobox"`) con opciones en formato `nombre/muestra` que
  provienen de `ProfileTypes`: `process_cpu/cpu`, `memory/alloc_objects`,
  `memory/alloc_space`, `memory/inuse_objects`, `memory/inuse_space`,
  `process_cpu/samples`. El valor persistido es el id completo de cinco campos
  (`memory/alloc_objects` → `memory:alloc_objects:count:space:bytes`).
- Cambiar el tipo re-dispara el preview (`SelectMergeStacktraces` → 200 con el nuevo
  perfil). **Apply** cierra el drawer con el cambio en memoria; **Save** (toolbar) emite
  `PUT /api/v1/projects/<proyecto>/dashboards/anomalia-stack` → **200** con
  `metadata.version` incrementado (v47 observado) y un `GET` posterior refleja el valor
  nuevo. El JSON pasa intacto por el proxy (`_rewrite_parses_content` solo reescribe
  HTML/JS/CSS) y `_parses_guard_path` deja el PUT por ser el proyecto propio.
- **Los cambios de UI no sobreviven al siguiente login**: `_ensure_dashboard`
  re-PUTea la plantilla resuelta en cada login, así que tras reautenticarse el `GET`
  vuelve al valor de la plantilla (observado: se restauró
  `process_cpu:cpu:nanoseconds:cpu:nanoseconds` solo con volver a entrar). *Save*
  sirve para cambios temporales durante la sesión; el cambio permanente se hace en
  `backend/dashboards/native/anomalia_stack.json` y reprovisionando.
- El botón `open query view for panel` (modo vista) abre el **Query Viewer** de solo
  lectura (`isReadonly: true`, único botón *Close*): no es un editor y no tiene
  *Apply*/*Save*.

**Búsqueda de trazas desde la cabecera (implementado 2026-10-03, e2e OK).** El
dashboard declara cinco `TextVariable` — `trace_id`, `trace_op`, `trace_tags`,
`trace_min_dur`, `trace_max_dur` (etiquetas visibles *Traza (trace ID)*, *Operacion*,
*Tags*, *Duracion min.*, *Duracion max.*) — cableadas así:

- `2_0` (TraceTable): `operation=$trace_op`, `tags=$trace_tags`,
  `minDuration=$trace_min_dur`, `maxDuration=$trace_max_dur`, con
  `service=anomalia_system` fijo. `traceId` **no** va en `2_0`: con `traceId` el
  lookup de TraceTable devuelve `{trace}` sin `searchResult` y el panel pinta
  *No data*; la búsqueda por ID va por `2_1` (Gantt, `traceId=$trace_id`).
- `JaegerTraceQuery.dependsOn` parsea esas variables del spec y las mete en el
  `queryKey`, y `resolveSpec` las sustituye con `variableState`: cambiar una variable
  re-dispara la query con el parámetro correspondiente (verificado end-to-end:
  `operation=GET /metrics`, `tags={"http.method":"GET"}`, `minDuration=1ms`,
  `maxDuration=10s`, traza real `a514bee9…` en el Gantt y error visible
  *valid JSON object* con tags no JSON).
- **La variable se aplica con blur (Tab o click fuera), no con Enter** — Enter deja
  el texto en el input sin commitear al store (verificado con Chrome headless). El
  `?var-trace_op=` de la URL también surte efecto al cargar.
- Las queries de panel se disparan tarde en este build (20–30 s tras abrir el
  dashboard): los e2e deben esperar a que haya filas antes de asertar.

**Por qué no hay selector de perfil Pyroscope en cabecera (verificado 2026-10-03).**
Test A/B capturando el `POST …/SelectMergeStacktraces`: con
`profileType: "process_cpu:…"` literal la query lleva el id correcto y el flamegraph
pinta; con `profileType: "$pyro_t"` (TextVariable `pyro_t` con valor
`memory:alloc_space:bytes:space:bytes`) la query llega a Pyroscope con
**`"profileTypeID":"$pyro_t"` literal** y el panel muestra *0.00 samples*. Causa: el
hook `ProfileQuery` del core inyecta al plugin solo
`{datasourceStore, absoluteTimeRange}` (**sin `variableState`**) y
`PyroscopeProfileQuery` no declara `dependsOn` ni llama `replaceVariables`
(con `get-profile-data.js`), así que `$vars` nunca se resuelven ni re-disparan la
query. En cambio `JaegerTraceQuery` y `PrometheusTimeSeriesQuery` sí lo hacen. Vías
válidas para elegir perfil: (a) **Edit → Query → Profile Type → Apply → Save** (solo
dura la sesión: `_ensure_dashboard` revierte), (b) el **panel dual** CPU/memoria del
dashboard, (c) **`/explore`** (ver siguiente bloque).

**`/explore` habilitada (cambio 2026-10-03, requiere repliegue del rol `parses`).**
`GET /api/config` devolvía `frontend.explorer.enable: false` y el guard de la ruta
redirigía al Home. El rol `parses` ahora copia `roles/parses/templates/config.yaml.j2`
a `/opt/anomalia/parses/config.yaml` (task *Copiar configuración de Perses*) y lo
monta read-only en `/etc/perses/config.yaml` (el entrypoint de la imagen es
`/bin/perses --config=/etc/perses/config.yaml`). El config solo declara
`database.file.folder` (igual que el de la imagen) y
`frontend.explorer.enable: {{ parses_explorer_enable | lower }}`, default `true` en
`defaults/main.yml`; verificado con un contenedor efímero que el resto de defaults
(security, plugin.path, auto_refresh) queda intacto. Estáticamente la ruta ya soporta
proyecto: el chunk de Explore lee el query param `project` (`useQueryParam("project")`)
y lo pasa como `projectName` a `DatasourceStoreProvider`, con lo que el selector de
datasources queda limitado a los del proyecto (`ds-metrics`, `ds-traces`,
`ds-profiles`, `ds-audit_logs`); sin el parámetro apunta a "Global", que no existe por
el aislamiento. En `/ui/{ticket}/explore?project=<proyecto>` el **PyroscopeExplorer**
expone el selector nativo de *Profile Type* (los 6 ids de la API `ProfileTypes`),
*Service* y filtros, que es donde se elige cualquier perfil sin editar el dashboard.

**`ui_tickets` no tiene job de purga** (solo INSERT/UPDATE/SELECT en
`ui_proxy_router.py`): las filas expiradas son inútiles —la cookie `anomalia_ui` solo
vale si `expires_at > now()` (`_session_from_request`)— y se pueden borrar para no
acumular; las vigentes respaldan sesiones abiertas y no se tocan.

## 10. Consecuencia de UX

Con provisioning por usuario, la lista de Perses muestra SOLO el project del usuario
(menos confuso que la variante "todo visible"). El navegador no conoce el token: Perses
server lo inyecta.

**Riesgo residual (verificado):** el token viaja **embebido** en la config del
datasource, y cualquier cliente que alcance la URL `/proxy/projects/<proyecto-ajeno>/
datasources/<datasource>/...` en Perses ejecuta la consulta **con el token del dueño**
del proyecto (se comprobó: un auditor obtuvo 200 sobre el datasource METRICS del admin).
Perses corre sin auth y expone su UI en `8090`, así que el aislamiento real entre
usuarios **depende de que Perses no sea alcanzable por terceros**. Mientras `8090` siga
abierto en la LAN, un atacante con la URL del proyecto de otro usuario lee sus tenants
hasta que venza el token del datasource.

**Punto de entrada desde Anomalia (actualizado 2026-10-01):** la tarjeta **Abrir
Parses** del índice ya no abre `http://<host>:8090/`. Pide un ticket con
`scope: "dashboards"` y el backend monta Perses bajo `/ui/{ticket}/`, con el
proyecto del usuario calculado igual que aquí (spec 010 §8). Eso cierra la entrada
habitual: quien llega a la UI ya pasó la sesión de Anomalia y el gating de perfil
`access_dasboards`, y las lecturas cruzadas se cortan en el proxy.

**Riesgo residual (el de la sección anterior no desaparece):** el `8090` sigue
publicado en `0.0.0.0` y Perses sigue sin auth. Quien alcance esa URL directamente
(la LAN, un libro de direcciones, una pestaña guardada) sigue pudiendo leer el
project de otro usuario si conoce su nombre, exactamente como antes. El token del
datasource y el firewall de Victoria limitan el alcance, no lo eliminan.

Mitigación efectiva = **F5**: retirar el `8090` de los puertos publicados y exponer
Perses solo detrás del gateway HTTPS autenticado de Anomalia, de modo que la única
puerta sea la del proxy. El proxy de consolas (spec 010 §8) ya hace esa labor para el
caso de uso normal; F5 sigue pendiente para eliminar el acceso crudo.

## 11. Fuera de alcance

- **F5**: Perses detrás del gateway HTTPS y `8090` sin publicar (hoy sigue en
  `0.0.0.0:8090`). El proxy de consolas cubre la entrada del dashboard pero no
  elimina el puerto. Pendiente para cerrar el riesgo de la sección 10.
- OIDC/SSO hacia Perses.
- Puertos de inserción/almacenamiento de Victoria detrás del firewall.
- Dashboards editados en Perses de vuelta a Git (los nativos sí viajan Git → Perses, ver § 9).
- `allowedEndpoints` **no** se fija en los datasources de Parses: Perses no restringe
  nada por su lado y el filtro real lo hace el backend (`HEADER_SCOPED_PREFIXES` y
  `_parses_guard_path`, § 7). Para acotarlo en Perses habría que listar los cinco
  endpoints POST `/querier.v1.QuerierService/...` (Pyroscope) y las rutas Jaeger,
  cuidando de no romper el plugin.
- APIs de vmselect `/pyroscope/*` (`/render`, `/labels`, `/series`, `/query`,
  `/merge`, `/appnames`): **fuera de la cadena**. El tenant PROFILES apunta a
  Pyroscope `:4040` (§ 2) y el plugin solo usa `querier.v1.QuerierService/*`.
- F4: auth/RBAC nativo de Perses para ocultamiento cosmético.