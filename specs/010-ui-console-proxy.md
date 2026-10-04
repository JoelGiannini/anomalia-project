# Spec 010 — Consolas de UI de telemetría por tenant (proxy autenticado)

## 1. Objetivo

Abrir las UIs de observabilidad (VictoriaMetrics, VictoriaTraces, VictoriaLogs,
Pyroscope y Parses/Perses) desde el dashboard de Anomalia **dentro del tenant o del
usuario que corresponda**, sin exponer los puertos de lectura a la LAN y sin que el
navegador tenga que transportar el JWT.

Decisiones aprobadas por el usuario en 2026-09-30:

1. **Camino A (proxy en el backend)**: el frontend pide un ticket opaco y navega a
   `/ui/redeem/{ticket}`; el backend reenvía la UI y todas sus llamadas al backend de
   lectura con el scoping del tenant inyectado. Se descartó nginx + `auth_request`
   porque el JWT vive en `localStorage` y `HTTPBearer` solo lee `Authorization`.
2. **Tarjetas con gating por perfil**: cada consola se habilita con un perfil concreto,
   chequeado tanto en el frontend como al emitir el ticket.
3. **Vida deslizante del ticket** (aprobado 2026-10-01 junto con el resto de la
   ronda de correcciones): el ticket se renueva mientras se use, en lugar de morir
   a los 5 minutos del canje.
4. **Marca de auditoría en la BD**: `tenants.is_audit`, no se deduce del `type`.
5. **Dashboards → Perses por el mismo proxy** (ronda 2026-10-01). Se revirtió la
   decisión original de abrir `http://<host>:8090/` a pelo: la tarjeta pide ahora un
   ticket con `scope: "dashboards"` y el backend monta Parses bajo `/ui/{ticket}/` con
   aislamiento por proyecto (ver §8). Perses sigue corriendo con `enable_auth: false`
   y con el `8090` publicado, pero la puerta de entrada habitual ya no es ese puerto.

## 2. Por qué no hay link directo

Dos impedimentos independientes, ambos verificados en vivo:

| Impedimento | Evidencia |
|---|---|
| Los puertos de lectura están aislados por firewall | `roles/victoria_firewall/defaults/main.yml` → `[8401, 8481, 8491, 4040]` solo desde `172.160.0.0/12`, `127.0.0.0/8` e IP del host. Un navegador de la LAN no puede alcanzarlos. |
| El JWT no viaja en la navegación | `main.js` lo guarda en `localStorage`; `auth.py` usa `HTTPBearer`, que solo lee `Authorization`. Abrir la UI en otra pestaña no envía credencial alguna. |

Además `FORCE_HTTPS=true` redirige `301` cualquier intento HTTP, y Perses/AIOps ya
dependen del TLS interno (spec 007).

## 3. Flujo

```
1. Frontend  POST /api/v1/ui/ticket  {tenant_id, scope}   (Authorization: Bearer)
2. Backend   valida JWT → perfil del scope (BD) → pertenencia del tenant (BD)
3. Backend   INSERT en ui_tickets y devuelve {url: "/ui/redeem/<ticket>"}
4. Navegador GET /ui/redeem/<ticket>      (sin credencial; único punto público)
5. Backend   marca el ticket consumido, setea cookie anomalia_ui (HttpOnly,
             path=/ui/<ticket>) y redirige 307 a /ui/<ticket><mount>
6. Navegador GET /ui/<ticket>/<ruta>      → proxy → read_url/<ruta>
```

El ticket es de **un solo uso** y su vida corre con `UI_TICKET_TTL_MINUTES`
(**30 minutos**), pero de forma **deslizante**: cada petición proxy que llega con
menos de `UI_TICKET_TOUCH_THRESHOLD_MINUTES` (la mitad) de vida restante empuja
`expires_at` a `now + TTL` y reemite la cookie, que comparte el mismo `max_age`.

Sin esa renovación la pestana moría a los cinco minutos del canje: el bundle seguía
reintentando `logsql/query` contra un `401`, el navegador pedía el documento como
navegador (Accept `text/html`) y recibía JSON crudo, y el resultado era una pantalla
en blanco con miles de 401 en la consola (≈2000/min por sesión). Cuando el ticket
acaba de verdad, el proxy ya no devuelve JSON: `_unauthorized_response` responde una
página HTML legible si la petición viene del navegador, o JSON si viene del fetch de
la propia UI. La cookie y el ticket caducan siempre juntos.

## 4. Endpoints

### `POST /api/v1/ui/ticket`

Requiere `Authorization: Bearer <JWT>`.

```json
{ "tenant_id": 1, "scope": "metrics" }
```

Respuesta `200`:

```json
{ "url": "/ui/redeem/9x…-…" }
```

Errores:

| Código | Causa |
|---|---|
| `400` | `scope` desconocido |
| `401` | Token inválido o usuario inexistente |
| `403` | Sin acceso al tenant, o sin el perfil que exige el `scope` |
| `404` | El tenant no tiene `tenant_datasources` habilitado |

### `GET /ui/redeem/{ticket}`

Único punto navegable sin credencial. Consume el ticket y redirige al `mount` de la
consola. Si el ticket es inválido/expirado devuelve `401` (HTML si lo pidió el
navegador, JSON si lo pidió un fetch).

Con scoping **por header** el `Location` añade además `?accountID=<a>&projectID=<p>`
tomados de `tenant_datasources`. vlui y vtui leen el tenant de la query string
(`e.get('accountID') || '0'`); sin esos parámetros la UI cree estar en `0:0` y su
selector de tenant no cuadra con el `tenant_ids` del backend. **No cambia el
scoping efectivo**: `_strip_scoping_params` los borra siempre antes de reenviar y los
headers reales salen de la BD, así que editar la URL no cambia de tenant.

### `GET|POST|PUT|PATCH|DELETE|OPTIONS /ui/{ticket}/{path:path}`

Proxy. Autenticación por **cookie** `anomalia_ui` o por `Authorization: Bearer`.

El `scope` guardado en la fila decide el upstream:

| `scope` | Upstream | Métodos |
|---|---|---|
| `metrics`, `logs`, `traces`, `profiling`, `audit` | `tenant_datasources.read_url` con el scoping inyectado | `GET`, `POST`, `OPTIONS` (el resto → `405`) |
| `dashboards` | `PARSES_UI_URL` (`http://parses:8080`) | `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS` |

`admin/tenants` es la única ruta admitida **fuera** del prefijo
`select/{acc}:{proj}/` en scoping por path: vmui la pide en la raíz de vmselect para
poblar su selector. Su respuesta pasa por `_filter_admin_tenants`, que recorta `data`
al tenant autorizado, de modo que no se filtran los IDs de los demás tenants.


## 5. Gating por perfil

El mismo tenant se abre desde varias tarjetas con permisos distintos, así que el
perfil **no** se deduce del `tenant_id`: viaja en `scope` y se resuelve en el backend
(`UI_SCOPE_PROFILE`).

| `scope` | Perfil requerido | Tarjeta | Sección |
|---|---|---|---|
| `metrics` | `access_metrics` | Abrir VictoriaMetrics | `view-metrics` |
| `logs` | `access_logs` | Abrir VictoriaLogs | `view-logs` |
| `traces` | `access_traces` | Abrir VictoriaTraces | `view-traces` |
| `profiling` | `access_Continuous_Profiling` | Abrir Pyroscope | `view-profiling` |
| `dashboards` | `access_dasboards` | Abrir Parses | `view-dashboards` |
| `audit` | `audit` | Abrir VictoriaLogs | `admin-view-audit` |

El chequeo se hace **contra la base** (`user_roles → role_profiles → profiles`), no
contra los claims del token, por la misma razón que `verify_tenant_access`: un token
con claims alterados no debe ampliar privilegios. El rol `admin` tiene todos los
perfiles sembrados, por lo que no necesita bypass. En el frontend,
`ui.renderTenants(tenants, roles, profiles)` oculta la tarjeta y muestra el perfil
requerido si el usuario no lo tiene; `ui.hasProfile()` replica la misma regla.

> **Historial de la tarjeta Dashboards.** En la ronda original se declaró `external`
> en `CONSOLES` y el botón hacía `window.open('http://<host>:8090/')` sin ticket, con
> `dashboards` fuera de `UI_SCOPE_PROFILE` (un `POST` con ese scope devolvía `400`).
> Se cambió porque exponía Perses por puerto crudo y sin el gating de perfil; hoy el
> scope está en la tabla y la tarjeta usa el mismo camino que el resto.

> Perses corre con `enable_auth: false` y su `8090` sigue publicado (spec 008 §10 y
> §11): el riesgo de abrir la URL a mano persiste, pero la entrada habitual del
> dashboard ya no la es.

### Marca de tenant de auditoría: `tenants.is_audit`

`AUDIT_LOGS` tiene `type = 'logs'`, como cualquier otro tenant de logs. Con un `match`
que solo miraba `type`, el tenant de auditoría aparecía **a la vez** en la pestaña
**Logs** y en la de **Auditoría**. Se añadió la columna
`tenants.is_audit BOOLEAN NOT NULL DEFAULT false` (sembrada `true` únicamente para
`AUDIT_LOGS`) y la bandera se expone en `GET /api/v1/tenants/my-tenants`:

```js
CONSOLES.logs.match  = t => !t.is_audit && (<type contiene "log">);
CONSOLES.audit.match = t => !!t.is_audit;
```

La columna vive en el DDL y en el `ON CONFLICT (name) DO UPDATE` de `init.sql.j2`.
El rol `backend` ejecuta `compose down -v` antes de `up`, así que el volumen de
PostgreSQL se recrea y el seed corre en cada deploy: no hace falta migración.

### Una pestaña visible a la vez y rejilla uniforme

`applyTabVisibility` (`backend/frontend/js/ui.js`) tiene dos condiciones distintas
que no deben confundirse:

- **disponible**: el tab tiene permiso (`visibleTabs.has(tab)`) → se oculta/muestra el
  botón `#tab-btn-{tab}`.
- **activa**: es la que el usuario abrió (`#main-tabs-container .tab-btn.border-current`)
  → se oculta/muestra `#view-{tab}`.

La condición es `hidden = !show || tab !== activeTab`. Antes solo se evaluaba `!show`,
con lo que `renderTenants` (que llama a `applyTabVisibility` al cargar, y **nunca** a
`switchTab`) le quitaba `hidden` a **todas** las secciones disponibles: el usuario veía
Métricas + Trazas + Perfilado + Dashboards a la vez, cada una con su cabecera y sus
tarjetas. La pestaña activa se lee **antes** de tocar la clase, y si estaba oculta se
salta a la primera visible (`switchTab`).

Rejilla: los cinco contenedores de `CONSOLES` usan la misma clase,
`grid grid-cols-1 md:grid-cols-3 gap-6`:

```html
<div id="metrics-tenants-container"   class="grid grid-cols-1 md:grid-cols-3 gap-6"></div>
<div id="logs-tenants-container"      class="grid grid-cols-1 md:grid-cols-3 gap-6"></div>
<div id="traces-container"            class="grid grid-cols-1 md:grid-cols-3 gap-6"></div>
<div id="profiling-container"         class="grid grid-cols-1 md:grid-cols-3 gap-6"></div>
<div id="dashboards-container"        class="grid grid-cols-1 md:grid-cols-3 gap-6"></div>
```

`traces` y `profiling` además **perdieron el envoltorio `.dynamic-card`** que metía la
cabecera de sección dentro de una tarjeta (por eso se veían a ancho completo y con un
tamaño distinto al resto); hoy las cinco secciones son hermanas: cabecera plana +
contenedor. `#alerts-container` se queda en `md:grid-cols-2`: es contenido estático de
la pestaña de Alertas y no pertenece a `CONSOLES`.

Las tarjetas marcadas dentro de `traces-container`, `profiling-container` y
`dashboards-container` en el HTML eran muertas (`renderTenants` reescribe
`container.innerHTML` completo) y ya no existen.

## 6. Scoping y validación de rutas

Los valores de aislamiento salen **siempre** de `tenant_datasources`; no se acepta
ningún valor del cliente. El modo de scoping cambia cómo se cierra la ruta:

### Scoping por path (VictoriaMetrics)

`read_url = http://host:8401`. El namespace va dentro de la ruta:
`/select/<accountID>:<projectID>/...`.

Sin validación, un usuario del tenant 1 podría pedir
`/ui/{tk}/select/999:999/prometheus/api/v1/query` y leer otro namespace. Por eso
`_validate_ui_path` **exige** que el path empiece por
`select/{account_id}:{project_id}/` construido desde la base, y devuelve `403` si no.

Si el datasource declara `scoping = path` con `account_id`/`project_id` nulos devuelve
`500`: es una configuración inválida, no un error del usuario.

### Scoping por header (VictoriaTraces, VictoriaLogs, Pyroscope)

El aislamiento va en headers (`AccountID`/`ProjectID`), que el proxy inyecta. Aun así
la ruta se limita por prefijo para que el proxy no sea un escape al resto de endpoints
del nodo (`UI_HEADER_PREFIXES`, análogo a `HEADER_SCOPED_PREFIXES` de
`parses_router`):

| Backend | Prefijos admitidos |
|---|---|
| VictoriaTraces | `select/` (cubre `vmui/`, `jaeger/…`) |
| VictoriaLogs | `select/` (cubre `vmui/`, `logsql/…`) |
| VictoriaMetrics (path) | `select/{acc}:{proj}/` **+** `admin/tenants` (respuesta recortada) |
| Pyroscope | `assets/`, `icons/`, `querier.v1.`, `pyroscope/`, `static/`, `favicon`, `manifest`, `robots`, `index.html` + raíz |

`icons/` entró tras ver `400 GET /ui/{tk}/icons/*.svg` en los logs: la SPA de
Pyroscope pide sus propios iconos y no estaban en la allowlist.

Además `_reject_path_traversal` bloquea `://` y `..`, para que la ruta no pueda
convertir al gateway en un proxy abierto hacia cualquier destino de la red de
contenedores, y `_strip_scoping_params` descarta `accountID`/`projectID`/`orgID`
del query string **siempre**, aunque el canje los haya inyectado.

## 7. Base URL derivada por cada UI (verificado empíricamente)

Ninguna de las cuatro se sirve "relativa a un prefijo" de forma uniforme. Se sondeó el
HTML y los bundles de cada una en vivo:

| Backend | Página | Derivación de base | `<base>` tag | Funciona bajo prefijo |
|---|---|---|---|---|
| VictoriaMetrics | `/select/0:0/vmui/` | `ve = h => h.replace(/(\/(?:prometheus\/)?(?:graph\|vmui)\/.*\|\/#\/.*)/, '/prometheus')` | no | ✅ |
| VictoriaTraces | `/select/vmui/` | `le = () => location.href.replace(/(\/(select\/)?vmui\/.*\|\/#\/.*)/, '')` → `serverUrl` | no | ✅ |
| VictoriaLogs | `/select/vmui` | ídem VictoriaTraces | no | ✅ |
| Pyroscope | `/` | `_()` lee `document.querySelector('base').getAttribute('href')` | **sí** | ✅ solo reescribiendo `<base>` |

**VictoriaMetrics.** `location.href = /ui/{tk}/select/0:0/vmui/` → base =
`/ui/{tk}/select/0:0/prometheus` → API en `/ui/{tk}/select/0:0/prometheus/api/v1/query`.
Los assets son relativos al documento (`./assets/…`) y resuelven bajo
`/select/0:0/vmui/assets/…`.

**VictoriaTraces / VictoriaLogs.** `serverUrl = le() = https://host/ui/{tk}` y las
llamadas se arman como `` `${serverUrl}/select/tenant_ids` `` o
`` `${serverUrl}/select/buildinfo` `` → caen bajo el prefijo y matchean `select/`.
Los assets relativos resuelven contra el documento (`/ui/{tk}/select/vmui/assets/…`).

**Pyroscope.** Es la única con `<base href="/" />`. La función `_()` del bundle hace:

```js
function _(){ let e=document.querySelector('base'); if(!e) return '';
  let t=e.getAttribute('href')??''; return t.includes('{{')||t==='/' ? '' : t.replace(/\/$/,'') }
```

Es decir: **si el `href` es `/` devuelve cadena vacía** (rutas absolutas a la raíz del
dominio); con cualquier otro valor devuelve ese prefijo. Por eso reescribir el atributo
arregla a la vez los assets y las llamadas RPC. Los métodos del bundle son los cinco de
`querier.v1.QuerierService`: `LabelNames`, `LabelValues`, `Series`, `SelectSeries`,
`SelectMergeStacktraces` (gRPC-web, `POST`).

`_rewrite_base_href` solo toca el HTML de Pyroscope y solo ese atributo; los bundles
JS no se modifican.

## 8. Consola de Parses (`scope = dashboards`)

Perses no es una UI de Victoria: no tiene `read_url` ni `tenant_datasources`. Su
upstream es fijo y sale de la variable de entorno `PARSES_UI_URL`
(`http://parses:8080`, el alias DNS del contenedor `anomalia_parses` en la red
`anomalia_aiops-net`).

Como `enable_auth: false`, **el aislamiento entre usuarios es responsabilidad del
proxy**: Perses no distingue a nadie, así que el proxy sí debe hacerlo.

### 8.1 Proyecto por usuario

`parses_project_name(username)` (función pública de `parses_provisioner`, la misma
que usa el provisionador) calcula
`anomalia-<sha256(username)[:10]>`. El `scope` no basta: dos usuarios con perfil
`access_dasboards` comparten el mismo `scope` y no deben verse entre sí. El proyecto
sale del `user_id` de la fila del ticket.

### 8.2 Cortes por ruta (`_parses_guard_path`)

| Ruta | Regla |
|---|---|
| `api/v1/projects` (listado) | `GET` → pasa; cualquier escritura → `403` (lo crea el provisionador) |
| `api/v1/projects/{otro}/…` | `404` con `{"message":"document not found"}` (no `403`: no se confirma que exista) |
| `api/v1/projects/{propio}` + `DELETE` | `403`: borrar el proyecto borría sus datasources y dashboards |
| `proxy/projects/{propio}/…` | pasa. Es el forward de datasource de Perses: el proyecto va en la ruta y Perses resuelve el datasource dentro de él |
| `proxy/projects/{otro}/…`, `proxy/…` sin proyecto | `404` |
| `api/v1/globaldatasources` | `GET` → pasa; escritura → `403` (no se usan) |
| Cualquier otra ruta (`main.js`, `locales/…`, `plugins/…`, `api/v1/dashboards`) | pasa; el filtrado de listados raíz lo hace la respuesta |

### 8.3 Cortes por cuerpo (`_parses_guard_body`)

1. Si hay `metadata.project` y no coincide con el propio → `404`. Cubre `POST`,
   `PUT` y `PATCH`.
2. **SSRF del datasource.** Perses guarda `spec.plugin.spec.proxy.spec.url` y la
   llama **desde dentro de la red** cuando el navegador hace `POST /proxy/…`. Un
   cliente que pudiera escribir esa URL convertiría a `parses` en un proxy abierto
   hacia `anomalia_postgres`, Victoria o el host. Se recorre todo el cuerpo
   buscando cualquier `proxy.spec.url` y solo se admite el que empieza por
   `PARSES_PROXY_BASE` (el gateway). `spec.plugin.spec.directUrl`, que hace que el
   propio navegador llame esa URL, también se rechaza. Se busca en todo el árbol,
   no en la raíz: un `PATCH` parcial trae el `spec` sin `kind` y sigue pudiendo
   cambiar la URL.

### 8.4 Aislamiento de la respuesta (`_parses_isolate_response`)

`GET` + `Content-Type: application/json` se filtra antes de devolverlo:

- El item tiene `metadata.project` y no es el propio → `404` (no se filtra un
  elemento de la lista: se corta la respuesta entera, como haría Perses).
- El item no tiene `metadata.project` (listado raíz plano como
  `/api/v1/dashboards`, `PluginModule`, respuestas de error) → se deja pasar.

`/api/v1/datasources` es el motivo crítico: además de los dashboards devuelve
`spec.plugin.spec.proxy.spec.headers`, con el **token de lectura del tenant**. Ahí el
filtrado no es solo coherencia de UI, es la única barrera contra la fuga. Verificado
en vivo: los cuatro datasources devuelven `X-Anomalia-Token` de 203 caracteres.

### 8.5 Reescritura de contenido (`_rewrite_parses_content`)

Perses resuelve todas sus URLs desde la raíz del dominio (`api_prefix` por defecto es
cadena vacía), así que servida bajo `/ui/{ticket}/` pediría `/main.js`, `/api/v1/…` y
`/plugins/…` a la raíz, donde no hay ruta. Se corrige en cinco puntos, y hay un sexto
que deliberadamente **no** se toca:

1. **HTML**: se inyecta `<script>window.PERSES_APP_CONFIG = { api_prefix: "/ui/{tk}" }</script>`
   antes del `<script defer src=…>` del bundle, y se reescriben `src="/…`,
   `href="/…` y `srcset` a `/ui/{tk}/…`. El inyecto es idempotente (si
   `PERSES_APP_CONFIG` ya está, no se repite).
2. **JS (`api_prefix`)**: el módulo `11042` declara `const i={api_prefix:""}` y lo
   exporta como `Ao.u`; el `<BrowserRouter basename>` lee `Ao.u.api_prefix`, **no**
   `window.PERSES_APP_CONFIG`. Como el bootstrap ya creó ese objeto, el `??` no
   reemplaza nada y el `basename` se queda vacío → la URL cae en
   `/projects/…` (fuera del ticket), refrescar sale de la consola y el `logout`
   (`window.location.href = ${api_prefix}/api/auth/logout`) apunta a la raíz. Se
   reescribe el literal `api_prefix:""` (1 ocurrencia de 8 `api_prefix` en
   `main.js`) a `api_prefix:"/ui/{tk}"`. Idempotente: una vez reescrito ya no
   queda el literal vacío.
3. **JS (`publicPath`)**: el runtime de rspack fija `a.p = "/"` y cada chunk se pide como
   `a.p + a.u(id)`, o sea en la raíz del origen (`https://anomalia.local/567.<hash>.js`
   en el error real `Loading chunk 567 failed`). Como el nombre de la variable está
   minificado y cambia en cada build, se busca la **asignación** (`(\w)\.p="/"` y
   `(\w)\.p=""`, una ocurrencia de cada una) y se la reescribe a `/ui/{tk}/`.
   Idempotente: una vez prefijado el valor ya no es `"/"` ni `""`.
4. **CSS**: `main.<hash>.css` apunta sus **84** `url(/<hash>.woff|woff2|…)` a la raíz del
   origen (las 404 de fuentes). Se reescribe `url(\s*["']?/` → `url(/ui/{tk}/` con un
   lookahead que evita doble prefijo; `url(data:…)` y rutas relativas no se tocan.
   Solo aplica a `text/css`; los binarios (`font/woff2`, imágenes) pasan sin reescribir.
5. **Red de seguridad**: el bootstrap parchea `fetch`/`XHR` para prefijar cualquier
   URL relativa a la raíz que no lleve ya el prefijo. El `publicPath` **no** cubre el
   parche: los chunks se piden con `document.createElement("script")` + `script.src`,
   que no pasa por `fetch`.
6. **JS (`"/plugins"`): NO se reescribe**. El `RemotePluginLoader` (`módulo 16271`)
   compone `pluginsAssetsPath = baseURL + c` con `c = "/plugins"`, y su **único**
   llamador (`módulo 18040`, presente en los chunks `368`/`526`) pasa
   `baseURL = Ao.u.api_prefix`. Con el literal reescrito (comportamiento anterior a
   este fix) la entrada del manifest salía como
   `/ui/{tk}/ui/{tk}/plugins/StatChart~0.15.0-beta.6/mf-manifest.json` y el runtime
   de Module Federation respondía
   `#RUNTIME-013: The manifest is not a valid Module Federation manifest`
   (`missingFields: metaData,exposes,shared`) en **todos** los paneles. El prefijo
   lo pone `baseURL`, así que el literal debe quedar intacto (las **2** ocurrencias
   del bundle). Tampoco se toca `"/api/v1/plugins"`: ese lo consume
   `pluginsApiPath = apiPrefix + l`, que ya lleva el prefijo por el punto 2.

Por qué basta (verificado sobre el build desplegado):

- `window.PERSES_APP_CONFIG` se declara con `??`, así que **nuestro objeto gana en
  `window`** (es el que lee el constructor `proxy.url` de los datasources, y también
  el `getPublicPath` de cada manifest, que devuelve
  `api_prefix + "/plugins/<nombre>/"`). Pero el módulo `11042` conserva su propio
  `i = {api_prefix:""}` y lo exporta como `Ao.u`, con lo que `window` y `Ao.u` son
  **dos objetos distintos**: por eso hace falta además la reescritura del literal
  del punto 2.
- El constructor de URLs de la API (`módulo 99219`) hace `const t = r.u.api_prefix`
  (o sea `Ao.u`) y antepone `api_prefix` a `/api/v1/...`, y la i18n hace lo mismo con
  `loadPath` (`{{lng}}.{{ns}}.json`).
- `módulo 67005` usa `api_prefix` para `/api/v1/view` y para
  `${api_prefix}/proxy/{…}`.
- `RemotePluginLoader` (`módulo 16271`) **sí** recibe argumentos:
  `u({baseURL: Ao.u.api_prefix, apiPrefix: Ao.u.api_prefix})`, único llamador
  (`módulo 18040`, chunks `368`/`526`). De ahí sale `pluginsAssetsPath`, ya con el
  prefijo, de modo que reescribir además el literal `"/plugins"` lo duplicaba
  (punto 6). `importPluginModule` pasa ese valor como `baseURL` a `Cr`, que arma la
  entrada `${baseURL || "/plugins"}/<módulo>~<versión>/mf-manifest.json`.
- El router de cliente usa `basename: Ao.u.api_prefix`: con el literal del punto 2
  reescrito, la navegación no sale de `/ui/{tk}/` y refrescar vuelve a servir la
  consola (sin él, la URL se queda en `/projects/…`, que ni siquiera arrastra la
  cookie del ticket).

### 8.6 Rutas de cliente (SPA fallback)

Si llega `GET` y Perses devuelve `404`, y la ruta **no** empieza por `api/` ni
`plugins/`, y su último segmento **no** lleva punto (`dashboards`,
`anomalia-8308ae92ec/dashboards/anomalia-stack`), se sirve `GET /` de Perses: es una
ruta que el router de cliente resuelve. Los `404` de API se respetan tal cual para no
disfrazarlos de página cargada.

### 8.7 Traversal y scoping

`..` y `://` se rechazan en la ruta antes de tocar nada (mismo criterio que
`_reject_path_traversal`). No se inyectan headers de scoping ni se reenvía la cookie
`anomalia_ui` hacia Perses: `forward_headers` queda vacío salvo `Content-Type`/
`Accept`, y el `accountID`/`projectID` del query string se siguen descartando.

## 9. Mount de cada consola

```python
UI_MOUNT_BY_KIND = {
    "VictoriaMetrics": "/select/{account_id}:{project_id}/vmui/",
    "VictoriaTraces":  "/select/vmui/",
    "VictoriaLogs":    "/select/vmui/",
    "Pyroscope":       "/",
}
```

El `mount` se usa **solo** en el redirect del canje. El proxy construye el upstream
como `read_url + "/" + path`: la ruta que llega ya es la ruta correcta respecto del
`read_url`, porque la UI la derivó de su propio `location.href`.

> **Trampa conocida:** `mount` reconstruido a mano en el upstream produce
> `/select/1:1/vmui/select/1:1/vmui/` (404). No se debe reutilizar el `mount` ahí.

`dashboards` no está en el mapa: `redeem_ui_ticket` lo detecta por el `scope` y
redirige a `/ui/{ticket}/` (raíz del ticket), que es donde Perses se monta.

## 10. Esquema

```sql
CREATE TABLE IF NOT EXISTS ui_tickets (
    id SERIAL PRIMARY KEY,
    ticket VARCHAR(128) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Alcance de la tarjeta que emitió el ticket (UI_SCOPE_PROFILE). Determina el
    -- upstream al que se monta la consola: los scopes de Victoria van a su UI,
    -- "dashboards" va a Parses.
    scope VARCHAR(32) NOT NULL DEFAULT 'metrics',
    expires_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ui_tickets_ticket ON ui_tickets(ticket);
CREATE INDEX IF NOT EXISTS idx_ui_tickets_expires ON ui_tickets(expires_at);
```

Definido en `ansible-infra/roles/backend/templates/init.sql.j2`.

## 11. Criterios de aceptación

- [ ] `POST /api/v1/ui/ticket` con perfil insuficiente → `403`.
- [ ] `POST` con `scope` inexistente → `400`.
- [ ] `/ui/{tk}/select/999:999/prometheus/api/v1/query` → `403` (tenant ajeno).
- [ ] `/ui/{tk}/…` sin cookie ni Bearer → `401`.
- [ ] Pestaña de Logs o Trazas **abierta más de 30 minutos** → sigue respondiendo
      `200`, sin bucle de `401` en la consola del navegador.
- [ ] Tras 30 minutos de inactividad, abrir la URL a mano → página HTML
      "La consola expiro" con enlace de vuelta, no JSON crudo.
- [ ] VL y VT muestran el tenant real en su selector (redirección con
      `accountID`/`projectID`), no `0:0`.
- [ ] Pyroscope: los assets, los cinco RPC `querier.v1.*` y `/icons/*.svg` responden
      bajo el prefijo.
- [ ] vmui pide `/admin/tenants` sin `403` y la respuesta lista solo el tenant del
      usuario.
- [ ] `GET /api/v1/tenants/my-tenants` trae `is_audit`; el tenant de auditoría no
      aparece en la pestaña Logs.
- [ ] La tarjeta **Abrir Parses** pide ticket y monta `/ui/{tk}/` (no `:8090`).
- [ ] Perses bajo `/ui/{tk}/`: el HTML trae `PERSES_APP_CONFIG.api_prefix`, los
      assets (`main.*.js`, `main.*.css`, `favicon`) cargan y `/plugins/` responde
      dentro del prefijo.
- [ ] `GET /ui/{tk}/main.<hash>.js` no contiene `.p="/"` ni `.p=""`: el `publicPath`
      ya está prefijado a `/ui/{tk}/` y doble petición idempotente.
- [ ] `GET /ui/{tk}/main.<hash>.js` contiene `api_prefix:"/ui/{tk}"` y **no** contiene
      `api_prefix:""`: el `basename` del router es el ticket.
- [ ] `GET /ui/{tk}/main.<hash>.js` **sí** conserva el literal `"/plugins"` intacto
      (2 ocurrencias, sin `/ui/{tk}/` delante): el prefijo lo pone
      `Ao.u.api_prefix` a través de `baseURL`.
- [ ] Al abrir un dashboard, la petición de manifest va a
      `/ui/{tk}/plugins/<Módulo>~<versión>/mf-manifest.json` con **un solo** prefijo
      (nunca `/ui/{tk}/ui/{tk}/…`), responde `200 application/json` con
      `metaData`/`exposes`/`shared` y la consola no muestra
      `#RUNTIME-013 … manifest is not a valid Module Federation manifest`.
- [ ] Abriendo un dashboard, la barra de dirección queda en
      `/ui/{tk}/projects/<proyecto>/dashboards/<n>`; refrescar esa URL sigue dentro
      de la consola (y arrastra la cookie del ticket).
- [ ] Abrir un dashboard que carga un chunk diferido → **sin**
      `Loading chunk N failed` (el chunk se pide en `/ui/{tk}/N.<hash>.js`).
- [ ] `GET /ui/{tk}/main.<hash>.css` no contiene `url(/` sin prefijo: las 84
      `url()` de fuentes responden `200` dentro del ticket.
- [ ] Dashboard con perfil de varias consolas: al cargar se ve **una sola** sección
      (la de la pestaña activa); `#view-metrics`/`#view-logs`/`#view-traces`/
      `#view-profiling`/`#view-dashboards` tienen `hidden` salvo la activa.
- [ ] Cambiar de pestaña deja exactamente una sección visible; ocultar la activa por
      perfil salta a la primera visible sin dejar el área vacía.
- [ ] Las cinco secciones usan `md:grid-cols-3`: en pantallas ≥768 px se ven 3 tarjetas
      por fila con el mismo tamaño y con la cabecera fuera de la tarjeta.
- [ ] `GET /ui/{tk}/api/v1/dashboards` solo lista dashboards del proyecto del
      usuario, y su respuesta **no** contiene `X-Anomalia-Token`.
- [ ] `GET /ui/{tk}/api/v1/projects/<proyecto-ajeno>/dashboards/<n>` →
      `404 {"message":"document not found"}`.
- [ ] `POST /ui/{tk}/api/v1/projects/<proyecto-ajeno>` → `404`; el mismo a
      `api/v1/projects` (listado) → `403`.
- [ ] `PUT` de un datasource con `proxy.spec.url` apuntando a `anomalia_postgres`
      → `403` (cuerpo sin `metadata.project` incluido: mismo resultado).
- [ ] `POST /ui/{tk}/api/v1/globaldatasources` → `403`.
- [ ] Crear/editar/borrar un dashboard propio con `PUT`/`POST`/`DELETE` → `200`.
- [ ] El ticket no vuelve a servir tras canjearlo ni tras 30 minutos de inactividad.

## 12. Operación

- **Sin certificado TLS** el proxy sigue funcionando: la cookie se emite con
  `secure = (scheme == https)` y el frontend accede por el gateway de clear-text.
- **Rotación** de CA/certs no afecta: el proxy habla por HTTP interno hacia
  `read_url` (spec 007).
- **Agregado de un backend nuevo**: alta en `UI_MOUNT_BY_KIND`,
  `UI_HEADER_PREFIXES`, `UI_SCOPE_PROFILE` y en `CONSOLES` de `frontend/js/ui.js`.
- **Agregado de una consola que no sea una UI de Victoria**: se resuelve por
  `scope` en `redeem_ui_ticket` y en `proxy_ui`, no por `UI_MOUNT_BY_KIND`. Es lo
  que hace `dashboards`.
- **Vida del ticket**: `UI_TICKET_TTL_MINUTES` (30) y
  `UI_TICKET_TOUCH_THRESHOLD_MINUTES` (15) en `ui_proxy_router.py`. Bajar el TTL sin
  bajar el umbral no rompe nada, pero la ventana de renovación se estrecha.
- **Variables de Parses**: `PARSES_UI_URL` (`http://parses:8080`) y
  `PARSES_PROXY_BASE` (del provisionador, idéntica a la del provisionador: el
  frontend y el proxy de UI deben coincidir). Ambas van en
  `roles/backend/templates/docker-compose.yml.j2`, en **los dos** servicios
  (`anomaliagw` y `anomaliagw_tls`).

## 13. Alcance pendiente fuera de esta spec

- La pestaña **Aprobaciones** tiene botón en el sidebar (`ui.js`) pero no existe la
  sección `admin-view-approvals` en `index.html`; al pulsarla la vista queda vacía.
  Es la misma falla que tenía Auditoría antes de este cambio y no se tocó por alcance
  atómico.
- El **puerto 8090 de Parses sigue publicado** (`0.0.0.0:8090->8080`). El proxy cubre
  la puerta de entrada del dashboard, no elimina la exposición de red: ver spec 008
  §10 y §11 (F5).
