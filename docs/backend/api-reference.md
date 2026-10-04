# Referencia de API Backend

El backend expone endpoints RESTful protegidos por autenticación OIDC/JWT y control de acceso basado en roles y perfiles.

## Routers Principales
- `/api/auth`: Autenticación y gestión de sesiones.
- `/api/admin`: Gestión de usuarios, roles, perfiles y tenants (`tenants_manager`).
- `/api/infrastructure`: Gestión de nodos de infraestructura (`infrastructure_nodes`). Expone `GET`, `PUT` y `DELETE`. La actualización por Ansible vive únicamente en `POST /api/v1/admin/infra/{node_id}/update`; el duplicado `POST /api/infrastructure/{node_id}/update` se retiró por apuntar a `127.0.0.1` hardcodeado y no ser consumido por ningún cliente (ver `specs/005` §2.7).
- `/api/v1/tenants`: Endpoints puente para consulta de tenants del usuario.
- `/api/v1/oidc`: CRUD de proveedores de identidad. Lo consume la app móvil.
- `/api/v1/ui` + `/ui`: Proxy autenticado de las consolas de Victoria (`specs/010`).

## `GET /api/v1/tenants/my-tenants`

Devuelve los tenants visibles para el usuario autenticado. Requiere `Authorization: Bearer <JWT>` (`verify_any_user_token`).

El acceso es la unión de asignación directa (`user_tenants`) y asignación por
cualquiera de los roles del usuario (`role_tenants`). **No hay bypass por rol**:
el admin accede por las filas sembradas para el rol `admin`, por lo que un
tenant nuevo debe asignarse explícitamente para ser visible.

```json
{
  "tenants": [
    {
      "id": 1,
      "name": "METRICS",
      "type": "metrics",
      "account_id": 0,
      "project_id": 0,
      "environment": "default",
      "port": 8400,
      "description": "...",
      "is_audit": false,
      "strategy": "numeric"
    }
  ]
}
```

`strategy` se deriva de `type` y define el aislamiento en vmauth:
`numeric` (`AccountID`/`ProjectID`) para `metrics`, `traces` y `logs`;
`x-scope-orgid` (`X-Scope-OrgID`) para `profiles`.

`is_audit` marca el tenant cuya telemetría es pista de auditoría (`tenants.is_audit`).
No se deduce de `type`: `AUDIT_LOGS` es `type = "logs"` como cualquier otro tenant de
logs, y con solo el `type` aparecía en la pestaña **Logs** y en **Auditoría** a la vez.

Ante error de base de datos devuelve `{"tenants": []}` en lugar de un 500, para
no romper el render del dashboard.

Detalle en `specs/007-https-gateway-and-tenant-access.md`.

## `POST /api/v1/ui/ticket`

Emite un ticket de un solo uso para abrir una consola en una pestaña nueva.
Requiere `Authorization: Bearer <JWT>`.

```json
{ "tenant_id": 1, "scope": "metrics" }
```

`scope` identifica la tarjeta desde la que se abre y determina el perfil exigido:
`metrics` · `logs` · `traces` · `profiling` · `dashboards` · `audit`.

Los cinco primeros montan la UI de Victoria correspondiente; `dashboards` monta
Perses (Parses) bajo el mismo prefijo de ticket, con el aislamiento por proyecto
de Perses y las escrituras (`PUT`/`POST`/`DELETE`) habilitadas.

```json
{ "url": "/ui/redeem/9x…-…" }
```

| Código | Causa |
|---|---|
| `400` | `scope` desconocido |
| `401` | Token inválido o usuario inexistente |
| `403` | Sin acceso al tenant o sin el perfil del `scope` |
| `404` | El tenant no tiene `tenant_datasources` habilitado |

El perfil y la pertenencia del tenant se resuelven **contra la base**
(`user_roles → role_profiles → profiles` y `user_tenants ∪ role_tenants`), no
contra los claims del token.

## `GET /ui/redeem/{ticket}`

Único punto navegable sin credencial. Consume el ticket, deja la cookie
`anomalia_ui` (HttpOnly, `path=/ui/{ticket}`, `max_age` de 30 minutos) y redirige
`307` al `mount` de la consola. Con scoping por header el `Location` lleva además
`?accountID=&projectID=` tomados de la BD, porque vlui/vtui leen el tenant de la
query string; el scoping efectivo no cambia, ya que esos parámetros se descartan
antes del upstream. Con `scope: "dashboards"` redirige a la raíz del ticket
(`/ui/{ticket}/`), que es donde se monta Perses. Devuelve `401` si el ticket es
inválido o expiró (HTML si lo pidió el navegador, JSON si lo pidió un fetch).

## `GET|POST|PUT|PATCH|DELETE|OPTIONS /ui/{ticket}/{path:path}`

Proxy hacia la consola que corresponda al `scope` del ticket. Autenticación por
cookie `anomalia_ui` o por `Authorization: Bearer`.

- Scopes de Victoria: el upstream es `read_url + "/" + path` y solo se admiten
  `GET`, `POST` y `OPTIONS` (`405` para el resto).
- `scope: "dashboards"`: el upstream es `PARSES_UI_URL` (`http://parses:8080`) y
  se admiten también `PUT`, `PATCH` y `DELETE` para que la UI edite dashboards.
- El aislamiento (`AccountID`/`ProjectID`) sale siempre de `tenant_datasources`.
- **Vida deslizante:** mientras al ticket le queden menos de 15 minutos de sus 30,
  cada petición válida renueva `expires_at` y reemite la cookie. Sin esto la pestaña
  dejaba de funcionar a los 5 minutos del canje y entraba en un bucle de `401`.
  Al vencer de verdad la respuesta es una página HTML de aviso, no JSON crudo.
- Para VictoriaMetrics el path debe empezar por
  `select/{account_id}:{project_id}/`, construido desde la base (`403` en caso
  contrario); la única excepción es `admin/tenants`, que vmui pide en la raíz para
  poblar su selector y cuya respuesta se recorta al tenant autorizado.
- Para el resto se limita por prefijo (`400`): Pyroscope admite además `icons/`.
- El HTML de Pyroscope se reescribe para cambiar `<base href="/" />` por
  `<base href="/ui/{ticket}/" />`, porque su bundle deriva la base de ese
  atributo tanto para assets como para las llamadas RPC.
- Con `dashboards`, Perses corre sin auth, así que el aislamiento lo pone el proxy:
  el proyecto sale de `parses_project_name(username)`, las lecturas de proyectos
  ajenos devuelven `404` con el formato de Perses, los listados raíz se filtran
  (incluido `/api/v1/datasources`, que lleva el token de lectura del tenant) y el
  HTML/JS se reescribe para que Perses use `/ui/{ticket}` como `api_prefix`.
  Además se rechazan cuerpos que apunten el `proxy.spec.url` de un datasource a
  cualquier sitio que no sea el gateway (SSRF).

Detalle en `specs/010-ui-console-proxy.md`.

