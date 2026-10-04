# Spec 007: Gateway HTTPS y Control de Acceso por Tenant

## 1. Objetivo

Separar dos responsabilidades de forma independiente y verificable:

1. **Canal de transporte**: que el gateway sirva la aplicación por HTTPS, con
   redirección desde HTTP, sin romper el scrapeo interno de vmagent.
2. **Aislamiento de datos**: que cada usuario vea únicamente los tenants para
   los que tenga concesión explícita, sin que el backend exponga la lista global.

---

## 2. Gateway HTTPS

### 2.1 Topología

El role `backend` despliega **dos** servicios FastAPI sobre la misma imagen:

| Servicio | Contenedor | Puerto host | Puerto interno | TLS |
|---|---|---|---|---|
| `anomaliagw` | `anomalia_gw` | `80`, `8000` | `8000` | no |
| `anomaliagw_tls` | `anomalia_gw_tls` | `443` | `8443` | sí |

`anomaliagw_tls` se renderiza **únicamente** si existe
`/opt/anomalia/certs/fullchain.pem`. La plantilla `docker-compose.yml.j2` resuelve
la condición con `certs_stat`, por lo que la ausencia de certificado degrada a
HTTP sin error de despliegue.

Ambos servicios montan el mismo código, `media/`, `playbooks/` y el socket de
Docker. `anomaliagw_tls` monta `/opt/anomalia/certs` en modo lectura.

### 2.2 Redirección

`main.py` define el middleware `enforce_https_redirect`, activo únicamente si
`FORCE_HTTPS=true` (inyectado por Ansible solo cuando hay certificado).

Exenciones deliberadas, para no romper la telemetría:

- **Rutas**: `/metrics` y `/healthz`. vmagent scrapea el gateway por HTTP en
  `backend_ip:8000/metrics`; redirigir esa ruta haría fallar el scrape.
- **Hosts**: `localhost`, `127.0.0.1`, `::1` y el Host ausente. Permiten
  desarrollo local en HTTP contra el mismo contenedor.

El destino se construye como `https://{host}:{PUBLIC_EXTERNAL_PORT}{path}`.

### 2.3 Materiales TLS

El role `certs` (`ansible-infra/roles/certs/`) materializa una **PKI de dos
niveles** — CA privada + certificado hoja — **solo si no existe**
(`creates:`), idempotente por construcción:

| Archivo | Contenido | Permisos |
|---|---|---|
| `ca.key` | clave privada de la CA (nunca sale del host) | `0600` |
| `ca.crt` | certificado de la CA, ancla de confianza | `0644` |
| `privkey.pem` | clave privada del leaf | `0600` |
| `leaf.crt` | certificado del leaf (`CA:FALSE`, `serverAuth`) | `0644` |
| `fullchain.pem` | `leaf.crt` + `ca.crt`, es lo que sirve uvicorn | `0644` |

- `openssl.cnf` renderizado con SAN para `certs_hostname`, `certs_extra_dns`
  (`localhost`, **`anomalia_gw_tls`**), `certs_ips` y la IP del nodo
  (`ansible_default_ipv4`).
- El leaf se firma con la CA y una validez de `certs_days`; la CA a
  `certs_ca_days`.
- El leaf y su CSR se generan en tareas separadas: al migrar de un
  autofirmado previo la clave ya existe pero el CSR no, y sin esa separación
  la firma fallaría por `leaf.csr` ausente.
- `fullchain.pem` se ensambla por contenido (`copy`), de modo que se regenera
  si cambian `leaf.crt` o `ca.crt`. El escalar de bloque en la plantilla
  garantiza el salto de línea entre ambos PEM.

**Por qué una CA separada**: el gateway es destino de confianza de un cliente
interno (Parses) que no puede usar el sistema de confianza del contenedor. La
CA permite entregarle el ancla por un `Secret` y que valide `fullchain.pem`
como cadena completa, en vez de anclarse a un leaf `CA:FALSE`. Ver spec 008 §7.

**Rotación**: los cambios de SAN o de clave no se detectan solos (las tareas
usan `creates:`). Para rotar explícitamente:

```bash
ansible-playbook -i inventory.ini -e certs_force=true deploy-infra.yml
```

`certs_force=true` borra `ca.key`, `ca.crt`, `ca.srl`, `privkey.pem`,
`leaf.csr`, `leaf.crt` y `fullchain.pem` antes de regenerar. Con el valor por
defecto (`false`) el material existente se conserva y el playbook no rota nada.
`destroy-infra.yml` **no** borra `/opt/anomalia/certs`, por lo que la rotación
requiere el `-e` explícito.

Variables (`roles/certs/defaults/main.yml`): `certs_hostname` (por defecto
`anomalia.local`), `certs_days`, `certs_ca_days`, `certs_key_size`,
`certs_dir`, `certs_extra_dns`, `certs_force`, `certs_country`, `certs_state`,
`certs_locality`, `certs_org`, `certs_ou`, `certs_ca_cn`.

**Promoción a producción**: sustituir los archivos por los de una CA real
(Let's Encrypt) y redeployar. Si se usa una CA externa, `PARSES_TLS_CA_FILE`
(ver spec 008 §7) debe apuntar al bundle de esa CA, y `certs_force` deja de
ser necesario. No requiere cambios de código; el formato de entrada es el
mismo.

---

## 3. Control de acceso por tenant

### 3.1 Modelo de concesión

El acceso de un usuario a un tenant es la **unión** de dos caminos:

```
user --user_tenants--> tenant          (asignación directa)
user --user_roles--> role --role_tenants--> tenant   (asignación por rol)
```

- `user_tenants(user_id, tenant_id)`: asignación directa.
- `role_tenants(role_id, tenant_id)`: asignación por rol.

**No existe bypass por rol en el código.** El admin accede por las filas
sembradas en `role_tenants` para el rol `admin`, por lo que la concesión es
auditable en la base. Consecuencia operativa: un tenant nuevo debe asignarse
explícitamente al rol `admin` (y a los roles que correspondan) o ningún
administrador lo verá.

Los roles se resuelven contra `user_roles` en la base, **nunca** contra los
claims del token, para que un JWT con roles alterados no amplíe privilegios.

### 3.2 Drift de esquema corregido

`user_tenants` existía en `backend/app/database.py` y en la base de datos en
ejecución, pero **faltaba en `ansible-infra/roles/backend/templates/init.sql.j2`**.
Una base creada desde cero por el playbook no habría tenido la tabla, y toda
consulta que la usara habría fallado. Se agregó a `init.sql.j2` declarada
después de `users` por su clave foránea.

### 3.3 Endpoint `GET /api/v1/tenants/my-tenants`

- **Auth**: `Depends(verify_any_user_token)`. Antes era público.
- **Identidad**: `payload["sub"]` o `payload["username"]`.
- **Driver**: `get_db_connection()` (psycopg2). La versión anterior declaraba
  `db: Session = Depends(get_db)` y ejecutaba `db.execute(text(...))` sobre una
  conexión cruda, lo que lanzaba excepción y terminaba en el `except` que
  devolvía `{"tenants": []}`: el endpoint nunca devolvía datos.
- **Degradación**: ante cualquier excepción devuelve `{"tenants": []}` en lugar
  de propagar un 500, para que el dashboard no se rompa.

Contrato de respuesta (se mantiene `{"tenants": [...]}` para no romper el
frontend):

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
      "strategy": "numeric"
    }
  ]
}
```

`strategy` se deriva de `type` (no se persiste) y define cómo vmauth aísla el
tenant:

| `type` | `strategy` | Mecanismo de aislamiento |
|---|---|---|
| `metrics`, `traces`, `logs` | `numeric` | `AccountID` + `ProjectID` |
| `profiles` | `x-scope-orgid` | header `X-Scope-OrgID` |

### 3.4 Dependencia `verify_tenant_access(tenant_id)`

Definida en `backend/app/auth.py`, misma forma que `verify_profile_access`.
Resuelve la misma unión de concessions y devuelve `403` si el usuario no tiene
acceso al tenant. **Declarada pero no conectada a ningún endpoint**: el gateway
de lectura de la Spec 004 la consumirá.

---

## 4. Retiro de Keycloak

Keycloak era una dependencia exclusiva de pruebas. Se retiró:

- El servicio `keycloak` de ambos `docker-compose.yml`.
- Las variables `OIDC_ISSUER_URL` y `KC_HOSTNAME` del gateway.
- `verify_oidc_token` de `auth.py` (sin referencias en el resto del código).
- El seeder de `oidc_providers`, que contenía el literal `change-me-secret`
  versionado en el repositorio, contrario a `constitution.md` §4.

**Se conserva** la tabla `oidc_providers` y el router `app/oidc.py`:
`mobile/lib/services/api_service.dart` los consume para dar de alta y editar
proveedores de identidad. Retirarlos rompería la app móvil.

Consecuencia: el botón "Acceder con Keycloak" del login web y el tab SSO del
panel de administración quedan sin backing. Ambos eran ya inertes: el endpoint
`/api/v1/oidc/login` que invocaba el login no existe en el backend, y el tab SSO
no tiene handler de guardado en `admin.js`.

---

## 5. Fuera de alcance

Esta spec no implementa, y queda para specs posteriores:

- vmauth con rutas dinámicas por tenant y recarga por `SIGHUP`
  (vmauth soporta `SIGHUP`, `/-/reload` y `-configCheckInterval`).
- Instancias de vmalert por tenant con puerto asignado.
- Gateway de lectura `/tenant/{id}/{tipo}` que consuma `verify_tenant_access`.
- Autenticación emissión de `AccountID`/`ProjectID` a clientes de ingesta.
