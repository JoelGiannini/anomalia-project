"""Provisioning por usuario de Perses, token de proxy y dashboards (spec 008).

En cada login el backend garantiza que en Perses exista un project por usuario con
un datasource por cada tenant al que el usuario tiene acceso. Cada datasource usa el
proxy HTTP de Perses hacia el gateway Anomalia e inyecta un token firmado de vida
corta (`purpose=parses-proxy`) en el header `X-Anomalia-Token` (Perses filtra el
header Authorization al reenviar por su HTTPProxy, verificado empiricamente).

Ademas, para los tenants de tipo METRICS se importan los dashboards fuente de
Grafana usando el endpoint `/api/migrate` del propio servidor de Perses y se fijan al
datasource del tenant. Se despliega ademas `backend/dashboards/native/*.json`, un
dashboard nativo de la plataforma que cubre la telemetria del propio backend
(metricas de `/metrics`, trazas OTLP y perfilado de CPU); sus queries declaran el tipo
de datasource requerido con el marcador `xAnomaliaDatasource`, que se resuelve contra
los datasources del usuario y descarta el panel si ese tipo no esta disponible.

El navegador nunca ve el token: Perses server es quien lo
agrega al consultar al backend. La identidad del usuario la vuelve a verificar el
backend en la BD por `sub`, no por claims confiables del cliente.

El proxy apunta al gateway por HTTPS (`PARSES_PROXY_BASE`), porque el gateway en
claro corre con `FORCE_HTTPS=true` y su middleware de redireccion devuelve 301
al proxy de Parses, que no puede seguirlo contra un puerto HTTP plano. Como el
certificado del gateway lo firma una CA privada, Parses la recibe en un `Secret`
de proyecto (`tlsConfig.ca`) referenciado por `proxy.spec.secret`: Perses exige
`Secret` y no `GlobalSecret` para los datasources de proyecto.
"""
import hashlib
import json
import os
import re
import logging
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Optional

import httpx
import jwt

from .auth import SECRET_KEY, ALGORITHM
from .database import get_db_connection

logger = logging.getLogger("anomalia.parses_provisioner")

# Base de la API REST de Perses y base URL del proxy Anomalia que recibira las queries.
PARSES_API_URL = os.getenv("PARSES_API_URL", "http://parses:8080/api/v1").rstrip("/")
# El endpoint de migracion NO vive bajo /api/v1: es `POST /api/migrate`.
PARSES_MIGRATE_URL = os.getenv(
    "PARSES_MIGRATE_URL",
    PARSES_API_URL.removesuffix("/v1"),
).rstrip("/")
PARSES_PROXY_BASE = os.getenv(
    "PARSES_PROXY_BASE",
    "https://anomalia_gw_tls:8443/api/v1/parses/datasources",
).rstrip("/")

# CA privada que firma el certificado del gateway, montada en solo lectura.
# Vacia = el gateway no tiene TLS: el proxy queda en http y no se crea Secret.
PARSES_TLS_CA_FILE = os.getenv("PARSES_TLS_CA_FILE", "").strip()

# Nombre del Secret de proyecto que lleva la CA del proxy.
PARSES_PROXY_SECRET_NAME = os.getenv("PARSES_PROXY_SECRET_NAME", "anomalia-proxy-ca")

# Vida del token de proxy (default 24h). Se re-emite en cada login; mantiene los
# datasources de Perses utilizables sin volver a iniciar sesion en el mismo dia.
PARSES_PROXY_TOKEN_TTL_SECONDS = int(os.getenv("PARSES_PROXY_TOKEN_TTL", "86400"))

PARSES_PROJECT_PREFIX = os.getenv("PARSES_PROJECT_PREFIX", "anomalia")

# Dashboards fuente de Grafana que se migran a Perses para los tenants METRICS.
# El role de backend copia `backend/` completo a /opt/anomalia/backend, asi que esta
# ruta llega al contenedor sin tocar Ansible.
GRAPHANA_DASHBOARDS_DIR = os.getenv(
    "PARSES_GRAFANA_DASHBOARDS_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboards", "grafana", "metrics")),
)

# Dashboards nativos de Anomalia (ya en modelo Perses, no se migran). Cubren la
# telemetria de la plataforma: metricas del backend, trazas OTLP y perfilado.
NATIVE_DASHBOARDS_DIR = os.getenv(
    "PARSES_NATIVE_DASHBOARDS_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboards", "native")),
)

# Cache del resultado de /api/migrate: la migracion es deterministica y depende solo
# del JSON fuente y de la logica de plugins del build fijado, no del usuario.
MIGRATED_CACHE_DIR = os.getenv(
    "PARSES_MIGRATED_CACHE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboards", "migrated")),
)

# Mapeo backend de almacenamiento -> plugin Datasource de Perses (verificado en 008).
PLUGIN_KIND_BY_STORAGE = {
    "VictoriaMetrics": "PrometheusDatasource",
    "VictoriaLogs": "VictoriaLogsDatasource",
    "VictoriaTraces": "JaegerDatasource",
    "Pyroscope": "PyroscopeDatasource",
}

# Prefijo de routing que se embebe en la URL del proxy para los backends con
# scoping por header (clúster Victoria). Solo aplica si el plugin NO lo trae ya en
# su propia ruta:
#   VictoriaTraces  -> plugin pide /api/services         (falta)   -> /select/jaeger
#   VictoriaLogs    -> plugin pide /select/logsql/query  (ya esta) -> ""
#   Pyroscope       -> plugin pide /querier.v1.QuerierService/... (raiz) -> ""
# Embeber un prefijo que el plugin ya trae produce una ruta doble que el upstream
# rechaza con 400 "unsupported path requested"; omitir el que falta produce 404.
# Verificado contra los upstreams reales y contra los chunks del build de Perses
# desplegado, no supuesto (spec 008).
HEADER_UPSTREAM_PREFIX_BY_STORAGE = {
    "VictoriaTraces": "/select/jaeger",
    "VictoriaLogs": "",
    "Pyroscope": "",
}


def user_tenant_rows(username: str) -> list[dict[str, Any]]:
    """Tenants con acceso del usuario: user_tenants ∪ role_tenants (resueltos en BD)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT t.id, t.name, t.type, d.kind, d.scoping, d.account_id, d.project_id, d.org_id
            FROM tenants t
            JOIN tenant_datasources d ON d.tenant_id = t.id AND d.enabled = TRUE
            WHERE t.id IN (
                SELECT ut.tenant_id
                FROM user_tenants ut
                JOIN users u ON u.id = ut.user_id
                WHERE u.username = %s
                UNION
                SELECT rt.tenant_id
                FROM role_tenants rt
                JOIN user_roles ur ON ur.role_id = rt.role_id
                JOIN users ru ON ru.id = ur.user_id
                WHERE ru.username = %s
            )
            ORDER BY t.id;
            """,
            (username, username),
        )
        rows = cursor.fetchall()
        return [
            {
                "tenant_id": r[0],
                "name": r[1],
                "type": r[2],
                "kind": r[3],
                "scoping": r[4],
                "account_id": r[5],
                "project_id": r[6],
                "org_id": r[7],
            }
            for r in rows
        ]
    finally:
        cursor.close()
        conn.close()


def mint_parses_token(username: str, tenant_ids: list[int], ttl_seconds: Optional[int] = None) -> str:
    """Token firmado para el proxy de datos de Parses (purpose=parses-proxy)."""
    to_encode: dict[str, Any] = {
        "sub": username,
        "purpose": "parses-proxy",
        "tenants": [int(t) for t in tenant_ids],
    }
    to_encode.update({
        "exp": datetime.utcnow() + timedelta(seconds=ttl_seconds or PARSES_PROXY_TOKEN_TTL_SECONDS),
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _project_name(username: str) -> str:
    digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:10]
    return f"{PARSES_PROJECT_PREFIX}-{digest}"


def parses_project_name(username: str) -> str:
    """Nombre del proyecto de Parses del usuario.

    Version publica de ``_project_name``: el proxy de UIs necesita el mismo
    calculo para aislar a cada usuario dentro de Perses, que corre con
    ``enable_auth: false``. Una sola fuente de verdad para los dos.
    """
    return _project_name(username)


def _datasource_name(tenant_name: str) -> str:
    return f"ds-{tenant_name.lower()}"


@lru_cache(maxsize=1)
def _proxy_ca_pem() -> str:
    """PEM de la CA que firma el certificado del gateway, o "" si no hay TLS."""
    if not PARSES_TLS_CA_FILE:
        return ""
    try:
        with open(PARSES_TLS_CA_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as exc:
        logger.warning("No se pudo leer la CA del proxy en %s: %s", PARSES_TLS_CA_FILE, exc)
        return ""


def _ensure_proxy_ca_secret(client: httpx.Client, project: str) -> Optional[str]:
    """Crea o actualiza el Secret de proyecto con la CA del proxy del gateway.

    Perses solo acepta `Secret` (con proyecto) para los datasources de proyecto:
    `GlobalSecret` no aplica. Devuelve el nombre del Secret para referenciarlo en
    `proxy.spec.secret`, o None si no hay CA (gateway sin TLS).
    """
    ca = _proxy_ca_pem()
    if not ca:
        return None

    payload = {
        "kind": "Secret",
        "metadata": {"name": PARSES_PROXY_SECRET_NAME, "project": project},
        "spec": {"tlsConfig": {"ca": ca}},
    }
    url = f"{PARSES_API_URL}/projects/{project}/secrets"
    existing = client.get(f"{url}/{PARSES_PROXY_SECRET_NAME}")
    if existing.status_code == 200:
        resp = client.put(f"{url}/{PARSES_PROXY_SECRET_NAME}", json=payload)
    else:
        resp = client.post(url, json=payload)
        if resp.status_code == 409:
            resp = client.put(f"{url}/{PARSES_PROXY_SECRET_NAME}", json=payload)

    if resp.status_code not in (200, 201):
        # error y no warning: sin este Secret los datasources HTTPS no podran
        # validar el certificado del gateway y las consultas fallaran por TLS.
        logger.error(
            "Secret de proxy '%s' NO se pudo garantizar en %s: %s %s",
            PARSES_PROXY_SECRET_NAME, project, resp.status_code, resp.text[:200],
        )
        return None
    logger.info("Secret de proxy '%s' garantizado en %s (%s).", PARSES_PROXY_SECRET_NAME, project, resp.status_code)
    return PARSES_PROXY_SECRET_NAME


def _datasource_payload(
    project: str,
    source: dict[str, Any],
    token: str,
    proxy_secret: Optional[str] = None,
    is_default: bool = False,
) -> Optional[dict[str, Any]]:
    plugin_kind = PLUGIN_KIND_BY_STORAGE.get(source["kind"])
    if not plugin_kind:
        logger.warning("Tenant %s sin plugin Datasource mapeado (kind=%s); se omite.", source["name"], source["kind"])
        return None

    upstream_prefix = HEADER_UPSTREAM_PREFIX_BY_STORAGE.get(source["kind"], "")

    proxy_spec: dict[str, Any] = {
        "url": f"{PARSES_PROXY_BASE}/{source['tenant_id']}{upstream_prefix}",
        # Header custom a proposito: Perses filtra el header Authorization al
        # reenviar por su HTTPProxy (008).
        "headers": {"X-Anomalia-Token": f"Bearer {token}"},
    }
    if proxy_secret:
        # CA con la que Perses valida el certificado del gateway en el proxy TLS.
        proxy_spec["secret"] = proxy_secret

    return {
        "kind": "Datasource",
        "metadata": {
            "name": _datasource_name(source["name"]),
            "project": project,
        },
        "spec": {
            # Perses resuelve un datasource sin `name` (el que usan las variables
            # ListVariable y las queries sin selector explicito) contra el que
            # tenga `default: true` de ese plugin. Sin ninguno, la resolucion
            # falla en silencio y las variables quedan vacias -> paneles "No data".
            # Solo el primer datasource de cada tipo lo recibe (ver provision_user_parses).
            "default": is_default,
            "plugin": {
                "kind": plugin_kind,
                "spec": {
                    "proxy": {
                        "kind": "HTTPProxy",
                        "spec": proxy_spec,
                    }
                },
            },
        },
    }


def _ensure_project(client: httpx.Client, name: str) -> None:
    if client.get(f"{PARSES_API_URL}/projects/{name}").status_code == 200:
        return
    resp = client.post(f"{PARSES_API_URL}/projects", json={"kind": "project", "metadata": {"name": name}})
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()
    logger.info("Project Parses '%s' garantizado (%s).", name, resp.status_code)


def _ensure_datasource(client: httpx.Client, payload: dict[str, Any], name: str, project: str) -> None:
    existing = client.get(f"{PARSES_API_URL}/projects/{project}/datasources/{name}")
    if existing.status_code == 200:
        resp = client.put(
            f"{PARSES_API_URL}/projects/{project}/datasources/{name}",
            json=payload,
        )
        if resp.status_code not in (200, 201):
            logger.warning("PUT datasource %s fallo: %s", name, resp.text)
    else:
        resp = client.post(f"{PARSES_API_URL}/datasources", json=payload)
        if resp.status_code not in (200, 201, 409):
            resp.raise_for_status()
        if resp.status_code == 409:
            client.put(
                f"{PARSES_API_URL}/projects/{project}/datasources/{name}",
                json=payload,
            )
    logger.info("Datasource Parses '%s' garantizado (%s).", name, resp.status_code)


_MIGRATION_PLACEHOLDER = "migration_from_grafana_not_supported"
_MIGRATION_UNSUPPORTED_VALUES = ["grafana", "migration", "not", "supported"]

# Se incluye en la clave de cache: si cambian las reglas de saneamiento, la cache
# de migraciones anteriores queda invalidada.
_SANITIZER_VERSION = "v1"


def _iter_grafana_panels(panels: Any):
    """Recorre paneles de forma recursiva (Grafana anida paneles en filas colapsadas)."""
    for panel in panels or []:
        yield panel
        yield from _iter_grafana_panels(panel.get("panels"))


def sanitize_grafana_dashboard(dashboard: dict[str, Any]) -> tuple[int, int]:
    """Adapta constructs de Grafana que el migrador de Perses no resuelve.

    Sin esto la migracion es atomica y un unico panel no soportado tumba el
    dashboard completo. Verificado contra el build fijado:

    1. `table` + `fieldConfig.defaults.thresholds` -> el panel Table de Perses no
       tiene equivalente numerico y falla con `_thresholdNumericSteps: undefined
       field: value`. Se descarta el umbral (degradacion solo cosmetica: el panel
       conserva datos y formato).
    2. `fieldConfig.overrides[].properties` con el mismo `id` repetido -> Perses
       construye un `querySettings` por query, no por serie, asi que dos
       `custom.lineStyle` (p.ej. solid y dash) colisionan con
       `conflicting values "dashed" and "solid"`. Se conserva el primero.

    Devuelve (thresholds descartados, overrides duplicados descartados).
    """
    thresholds_dropped = 0
    duplicates_dropped = 0

    for panel in _iter_grafana_panels(dashboard.get("panels")):
        field_config = panel.get("fieldConfig") or {}

        if panel.get("type") == "table":
            defaults = field_config.get("defaults") or {}
            if isinstance(defaults, dict) and defaults.pop("thresholds", None) is not None:
                thresholds_dropped += 1

        seen: set[str] = set()
        for override in field_config.get("overrides") or []:
            kept = []
            for prop in override.get("properties") or []:
                prop_id = prop.get("id")
                if prop_id in seen:
                    duplicates_dropped += 1
                    continue
                seen.add(prop_id)
                kept.append(prop)
            override["properties"] = kept

    return thresholds_dropped, duplicates_dropped


def _query_placeholder_report(dashboard: dict[str, Any]) -> tuple[int, int]:
    """Cuenta (queries totales, queries placeholder) del dashboard migrado."""
    total = 0
    placeholders = 0
    for panel in (dashboard.get("spec", {}) or {}).get("panels", {}).values() or []:
        for query in (panel.get("spec") or {}).get("queries") or []:
            total += 1
            if _MIGRATION_PLACEHOLDER in json.dumps(query):
                placeholders += 1
    return total, placeholders


def migrate_grafana(client: httpx.Client, path: str) -> Optional[dict[str, Any]]:
    """Traduce un dashboard de Grafana al modelo Perses via POST /api/migrate.

    El resultado se cachea por sha256 del archivo fuente: la traduccion no depende
    del usuario ni del proyecto, asi que se calcula una sola vez por dashboard.
    """
    try:
        raw = open(path, "rb").read()
    except OSError:
        logger.warning("No se pudo leer el dashboard fuente %s", path)
        return None

    digest = hashlib.sha256(raw).hexdigest()
    cache_path = os.path.join(MIGRATED_CACHE_DIR, f"{digest}.{_SANITIZER_VERSION}.json")
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        if isinstance(cached, dict) and cached.get("kind") == "Dashboard":
            return cached
    except (OSError, ValueError):
        pass

    try:
        grafana_dashboard = json.loads(raw)
    except ValueError as exc:
        logger.warning("JSON invalido en %s: %s", path, exc)
        return None

    thresholds, duplicates = sanitize_grafana_dashboard(grafana_dashboard)
    if thresholds or duplicates:
        logger.info(
            "Saneado de %s: %s umbrales de tabla y %s overrides duplicados descartados.",
            os.path.basename(path), thresholds, duplicates,
        )

    resp = client.post(f"{PARSES_MIGRATE_URL}/migrate", json={"grafanaDashboard": grafana_dashboard})
    if resp.status_code not in (200, 201):
        logger.warning("Migrate fallo para %s: %s %s", path, resp.status_code, resp.text[:200])
        return None

    migrated = resp.json()
    panels = len(migrated.get("spec", {}).get("panels", {}))
    logger.info("Dashboard '%s' migrado a Perses (%s paneles).", os.path.basename(path), panels)

    try:
        os.makedirs(MIGRATED_CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(migrated, fh)
    except OSError as exc:
        logger.debug("No se pudo cachear la migracion de %s: %s", path, exc)
    return migrated


def bind_metrics_datasource(dashboard: dict[str, Any], datasource_name: str) -> int:
    """Fija el datasource del tenant en un dashboard migrado.

    /api/migrate deja la variable de datasource como `DatasourceVariable` (un
    dropdown vacio en la UI). Se reemplaza por una `StaticListVariable` con un unico
    valor, de modo que todas las queries que referencian `$<variable>` resuelven al
    datasource provisionado del tenant.

    De paso oculta las variables que el migrador no sabe traducir (adhoc filters y
    similares, que quedan con los valores `grafana/migration/not/supported`): son
    widgets muertos que solo confunden al usuario.

    Devuelve cuantos bindings se aplicaron (0 = el dashboard no trae selector de
    datasource, por ejemplo solo variables de label).
    """
    bound = 0
    for variable in (dashboard.get("spec", {}) or {}).get("variables", []) or []:
        spec = variable.get("spec") or {}
        plugin = spec.get("plugin") or {}

        if plugin.get("kind") == "DatasourceVariable":
            spec["plugin"] = {
                "kind": "StaticListVariable",
                "spec": {"values": [datasource_name]},
            }
            spec["defaultValue"] = datasource_name
            spec["allowAllValue"] = False
            spec["allowMultiple"] = False
            spec.setdefault("display", {})["hidden"] = True
            bound += 1
        elif (
            plugin.get("kind") == "StaticListVariable"
            and (plugin.get("spec") or {}).get("values") == _MIGRATION_UNSUPPORTED_VALUES
        ):
            spec.setdefault("display", {})["hidden"] = True
    return bound


def _normalize_list_variable_defaults(dashboard: dict[str, Any]) -> int:
    """Restaura el valor por defecto ``$__all`` de las variables de lista.

    Perses representa la opcion "All" con la cadena ``$__all`` (no con una lista).
    El migrador de /api/migrate deja dos situaciones que impiden que las variables
    arranquen con todas las opciones seleccionadas:

      - ``defaultValue: ["$__all"]`` (lista heredada de ``current.value`` de
        Grafana): el valor no coincide con la opcion "All" y se usa literalmente
        como valor de la variable (``job=~"$__all"`` -> sin coincidencias);
      - sin ``defaultValue``: Perses selecciona la primera opcion, asi que los
        paneles quedan filtrados a un unico job/instance.

    Devuelve cuantas variables se tocaron.
    """
    patched = 0
    for variable in (dashboard.get("spec", {}) or {}).get("variables", []) or []:
        spec = variable.get("spec") or {}
        kind = (spec.get("plugin") or {}).get("kind")
        if kind in ("StaticListVariable", "DatasourceVariable"):
            continue
        default = spec.get("defaultValue")
        if isinstance(default, list):
            if "$__all" in default:
                spec["defaultValue"] = "$__all"
                patched += 1
        elif default is None and spec.get("allowAllValue"):
            spec["defaultValue"] = "$__all"
            patched += 1
    return patched


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "dashboard"


def _ensure_dashboard(client: httpx.Client, project: str, name: str, payload: dict[str, Any]) -> None:
    existing = client.get(f"{PARSES_API_URL}/projects/{project}/dashboards/{name}")
    if existing.status_code == 200:
        resp = client.put(f"{PARSES_API_URL}/projects/{project}/dashboards/{name}", json=payload)
    else:
        resp = client.post(f"{PARSES_API_URL}/dashboards", json=payload)
        if resp.status_code == 409:
            resp = client.put(f"{PARSES_API_URL}/projects/{project}/dashboards/{name}", json=payload)
    if resp.status_code not in (200, 201):
        logger.warning("Alta de dashboard %s fallo: %s %s", name, resp.status_code, resp.text[:200])


def _provision_metrics_dashboards(
    client: httpx.Client,
    project: str,
    tenant: dict[str, Any],
    datasource_name: str,
) -> list[str]:
    """Migra y publica los dashboards fuente de Grafana para un tenant METRICS."""
    if not os.path.isdir(GRAPHANA_DASHBOARDS_DIR):
        logger.info("Sin dashboards fuente en %s", GRAPHANA_DASHBOARDS_DIR)
        return []

    deployed: list[str] = []
    for filename in sorted(os.listdir(GRAPHANA_DASHBOARDS_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(GRAPHANA_DASHBOARDS_DIR, filename)
        migrated = migrate_grafana(client, path)
        if migrated is None:
            continue

        total_queries, placeholder_queries = _query_placeholder_report(migrated)
        if total_queries and placeholder_queries == total_queries:
            logger.warning(
                "Dashboard '%s' omitido: sus %s queries dependen de un datasource de "
                "Grafana que Perses no traduce (se migran a '%s'). Requiere el plugin "
                "de origen, no PromQL.",
                filename, total_queries, _MIGRATION_PLACEHOLDER,
            )
            continue
        if placeholder_queries:
            logger.warning(
                "Dashboard '%s': %s de %s queries quedaron como placeholder y no "
                "mostraran datos.", filename, placeholder_queries, total_queries,
            )

        stem = os.path.splitext(filename)[0]
        # El nombre incluye el datasource para que un usuario con varios tenants
        # METRICS tenga un juego de dashboards por tenant, sin colisiones.
        name = f"{_slug(stem)}--{datasource_name}"
        bound = bind_metrics_datasource(migrated, datasource_name)
        defaults = _normalize_list_variable_defaults(migrated)
        migrated["metadata"]["name"] = name
        migrated["metadata"]["project"] = project
        display = migrated.get("spec", {}).get("display", {})
        if isinstance(display, dict) and display.get("name"):
            display["name"] = f"{display['name']} ({datasource_name})"

        _ensure_dashboard(client, project, name, migrated)
        deployed.append(name)
        logger.info(
            "Dashboard '%s' desplegado con datasource %s (%s bindings, %s defaults de variables).",
            name, datasource_name, bound, defaults,
        )
    return deployed


def provision_native_dashboards(
    client: httpx.Client,
    project: str,
    datasources_by_kind: dict[str, str],
) -> list[str]:
    """Publica los dashboards nativos de Anomalia, resolviendo sus datasources.

    Cada query del template declara el tipo de datasource que necesita con el marcador
    `xAnomaliaDatasource`. Se reemplaza por el selector concreto
    `{"kind": ..., "name": ...}` del datasource del usuario. Los paneles cuyo tipo de
    datasource no esta disponible (el usuario no tiene ese tenant) se descartan: es
    preferible un dashboard con menos secciones que uno con paneles rotos.
    """
    if not os.path.isdir(NATIVE_DASHBOARDS_DIR):
        logger.info("Sin dashboards nativos en %s", NATIVE_DASHBOARDS_DIR)
        return []

    deployed: list[str] = []
    for filename in sorted(os.listdir(NATIVE_DASHBOARDS_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(NATIVE_DASHBOARDS_DIR, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                dashboard = json.load(fh)
        except (OSError, ValueError) as exc:
            logger.warning("Dashboard nativo ilegible %s: %s", path, exc)
            continue

        panels: dict[str, Any] = {}
        dropped: list[str] = []
        for key, panel in (dashboard.get("spec", {}).get("panels", {}) or {}).items():
            if not _resolve_panel_datasources(panel, datasources_by_kind):
                dropped.append((panel.get("spec", {}).get("display", {}) or {}).get("name", key))
                continue
            panels[key] = panel

        if not panels:
            logger.info("Dashboard nativo '%s' omitido: el usuario no tiene ningun datasource aplicable.", filename)
            continue

        dashboard["spec"]["panels"] = panels
        name = dashboard.get("metadata", {}).get("name") or os.path.splitext(filename)[0]
        dashboard["metadata"]["name"] = name
        dashboard["metadata"]["project"] = project

        _ensure_dashboard(client, project, name, dashboard)
        deployed.append(name)
        if dropped:
            logger.info(
                "Dashboard nativo '%s': %s de %s paneles (sin datasource: %s).",
                name, len(panels), len(panels) + len(dropped), ", ".join(dropped),
            )
        else:
            logger.info("Dashboard nativo '%s' desplegado con %s paneles.", name, len(panels))
    return deployed


def _resolve_panel_datasources(panel: dict[str, Any], datasources_by_kind: dict[str, str]) -> bool:
    """Sustituye los marcadores `xAnomaliaDatasource` por selectores reales.

    Devuelve False si al panel le falta algun datasource requerido.
    """
    for query in (panel.get("spec", {}) or {}).get("queries", []) or []:
        spec = ((query.get("spec") or {}).get("plugin") or {}).get("spec") or {}
        required = spec.pop("xAnomaliaDatasource", None)
        if not required:
            continue
        name = datasources_by_kind.get(required)
        if not name:
            return False
        spec["datasource"] = {"kind": required, "name": name}
    return True


def provision_user_parses(username: str) -> dict[str, Any]:
    """Idempotente: crea/actualiza el project, datasources y dashboards del usuario.

    Se ejecuta en background tras el login o en el catch-up de arranque (spec 008).
    Una falla aqui NO debe impedir el login: el caller es responsable de tolerar
    excepciones. Ante errores transitorios (Parses aún arrancando, 5xx, timeout)
    se reintenta hasta 3 veces con backoff; el provisioning es idempotente
    (GET->POST/PUT) por lo que re-ejecutar el bloque es seguro.
    """
    backoff = [3, 6]  # segundos de espera entre intentos
    last_error: Optional[Exception] = None
    outputs: dict[str, Any] = {
        "project": _project_name(username),
        "datasources": [],
        "dashboards": [],
        "native_dashboards": [],
        "error": None,
    }
    for attempt in range(1, 4):
        try:
            tenants = user_tenant_rows(username)
            project = _project_name(username)
            token = mint_parses_token(username, [t["tenant_id"] for t in tenants])
            outputs["project"] = project
            with httpx.Client(timeout=30.0) as client:
                _ensure_project(client, project)
                proxy_secret = _ensure_proxy_ca_secret(client, project)
                datasources_by_kind: dict[str, str] = {}
                for source in tenants:
                    # El primer datasource de cada tipo es el default de Perses y el
                    # que usan los dashboards nativos (uno por tipo, no uno por tenant).
                    kind = PLUGIN_KIND_BY_STORAGE.get(source["kind"])
                    is_default = bool(kind) and kind not in datasources_by_kind
                    payload = _datasource_payload(project, source, token, proxy_secret, is_default)
                    if payload is None:
                        continue
                    ds_name = payload["metadata"]["name"]
                    _ensure_datasource(client, payload, ds_name, project)
                    outputs["datasources"].append(source["name"])
                    datasources_by_kind.setdefault(payload["spec"]["plugin"]["kind"], ds_name)

                    if (source["type"] or "").lower() == "metrics":
                        outputs["dashboards"].extend(
                            _provision_metrics_dashboards(client, project, source, ds_name)
                        )

                outputs["native_dashboards"].extend(
                    provision_native_dashboards(client, project, datasources_by_kind)
                )
            break
        except Exception as exc:  # noqa: BLE001 - no debe tumbar el login
            last_error = exc
            logger.warning(
                "Provision Parses para %s: intento %s/3 falló (%s%s)",
                username, attempt, type(exc).__name__,
                " - reintentando" if attempt < 3 else "",
            )
            if attempt < 3:
                time.sleep(backoff[attempt - 1])
    else:
        logger.exception("No se pudo provisionar Parses para %s", username)
        outputs["error"] = str(last_error)
    return outputs