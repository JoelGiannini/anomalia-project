# Arquitectura General

Anomalia está diseñada bajo una arquitectura modular y multitenant orientada a microservicios e infraestructura distribuida.

## Componentes del Sistema
1. **Backend API:** FastAPI (Python) para lógica de negocio, RBAC, gestión de tenants y webhooks.
2. **Base de Datos:** PostgreSQL 15 para persistencia transaccional.
3. **Observabilidad:** VictoriaMetrics, VictoriaLogs, VictoriaTraces, Pyroscope, vmalert, Alertmanager, Parses.
4. **Interfaces:** Panel Web Vanilla JS y App Móvil Flutter.

## Parses (dashboards por usuario)

Perses se provisiona **por usuario** en cada login: un project
`anomalia-<hash>` con un datasource por tenant al que el usuario tiene acceso y dos
tipos de dashboards — los **migrados de Grafana** con los dashboards de la
infraestructura (tenants METRICS) y `anomalia-stack`, el **dashboard nativo** que
muestra la telemetría del propio backend (métricas de `/metrics`, trazas OTLP y
perfilados de CPU y memoria). El dashboard trae **filtros de trazas en la cabecera**
(traza por ID → Gantt, operación, tags, duración mín/máx) que se aplican al salir del
campo (blur), y la página `/explore` queda habilitada con el selector nativo de
perfiles de Pyroscope. Los datasources se sirven vía el proxy HTTP de Perses hacia el
gateway con token de vida corta. Detalle en `specs/008-parses-datasources-and-tenant-scoping.md`.

Los dashboards se editan desde la propia consola: **Edit** → editor de panel con
**preview de queries en vivo** (pestaña *Query*, con ~10-15 s de carga de plugins hasta
que aparecen las pestañas) → **Apply** → **Save**, que hace un `PUT` sobre el proyecto
propio. Como la plantilla se re-provisiona en cada login, los cambios de UI duran lo que
dure la sesión; los permanentes se hacen en `backend/dashboards/native/anomalia_stack.json`.
La página `/explore` se habilita con `frontend.explorer.enable: true` (config de Perses
montado por el rol `parses`, ver `specs/008` §9).

## Consolas de Victoria (proxy de tickets)

Las UIs de VictoriaMetrics, VictoriaTraces, VictoriaLogs y Pyroscope se abren
desde el panel **dentro del tenant del usuario**. No hay link directo: los
puertos de lectura (8401/8481/8491/4040) están aislados por firewall y el JWT
vive en `localStorage`, por lo que no viajaría en la navegación.

El flujo es: el frontend pide un ticket con su JWT
(`POST /api/v1/ui/ticket {tenant_id, scope}`) → el backend exige el perfil del
`scope` y la pertenencia del tenant, contra la base → el navegador navega a
`/ui/redeem/{ticket}` (único punto sin credencial) → se consume el ticket, se
deja una cookie `HttpOnly` de 30 minutos y se redirige a
`/ui/{ticket}/{ruta}` → el proxy reenvía al `read_url` del tenant con el
aislamiento inyectado. La vida del ticket es **deslizante**: se renueva mientras
la pestaña siga en uso, de modo que una consola abierta no muere por el reloj.

Cada tarjeta exige su perfil (`access_metrics`, `access_logs`, `access_traces`,
`access_Continuous_Profiling`, `access_dasboards`, `audit`), chequeado tanto en
`frontend/js/ui.js` como al emitir el ticket. La tarjeta **Dashboards** usa el
mismo camino con `scope: "dashboards"`: el backend monta Perses (Parses) bajo
`/ui/{ticket}/` y pone el aislamiento por proyecto, porque Perses corre sin
autenticación propia.

Detalle en `specs/010-ui-console-proxy.md`.

## Gateway HTTPS

El role `backend` despliega dos instancias de la misma imagen FastAPI:

| Servicio | Puertos host | TLS | Función |
|---|---|---|---|
| `anomaliagw` | `80`, `8000` | no | Redirige a HTTPS; sirve en claro si no hay certificado |
| `anomaliagw_tls` | `443` | sí | Sirve la aplicación |

`anomaliagw_tls` solo se crea si existe `/opt/anomalia/certs/fullchain.pem`, que
genera el role `certs` de forma idempotente.

La redirección `FORCE_HTTPS` exime `/metrics` y `/healthz` porque vmagent
scrapea el gateway por HTTP en `backend_ip:8000/metrics`, y exime los hosts de
loopback para permitir desarrollo local.

Detalle en `specs/007-https-gateway-and-tenant-access.md`.

