"""Vmalert worker: processes vmalert_deploy, vmalert_undeploy, vmalert_redeploy, vmalert_reload, vmalert_sync_rules, vmalert_regen_scrapes jobs."""
import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from typing import Optional

import httpx

from .base import BaseWorker
from ..database import get_db_connection
from ..internal_rules import INTERNAL_RULES

logger = logging.getLogger("anomalia.workers.vmalert")

RELOAD_ATTEMPTS = 3
RELOAD_TIMEOUT_SECONDS = 10.0

# Puertos por defecto por componente (spec 011 §4.3/§4.4): usados por el regen
# de scrapes cuando infrastructure_nodes no fija port para un componente.
PORT_DEFAULTS = {
    'vlstorage': 8482, 'vlinsert': 8480, 'vlselect': 8481,
    'vmstorage': 8402, 'vminsert': 8400, 'vmselect': 8401,
    'vtstorage': 8492, 'vtinsert': 8490, 'vtselect': 8491,
    'pyroscope': 4040, 'vmauth': 8427, 'vmagent': 8429,
    'alertmanager': 9093, 'vmalert': 8880,
    'backend': 8000, 'parses': 8090,
}


class VmalertWorker(BaseWorker):
    """Worker that handles vmalert deployment jobs."""

    def __init__(self, interval: int = 30):
        super().__init__(
            interval,
            job_types=[
                'vmalert_deploy', 'vmalert_undeploy', 'vmalert_redeploy',
                'vmalert_reload', 'vmalert_sync_rules', 'vmalert_regen_scrapes',
            ]
        )

    async def process_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        if job_type == 'vmalert_deploy':
            await self._process_vmalert_deploy(job_id, ref_id, payload)
        elif job_type == 'vmalert_undeploy':
            await self._process_vmalert_undeploy(job_id, ref_id, payload)
        elif job_type == 'vmalert_redeploy':
            await self._process_vmalert_redeploy(job_id, ref_id, payload)
        elif job_type == 'vmalert_reload':
            await self._process_vmalert_reload(job_id, ref_id, payload)
        elif job_type == 'vmalert_sync_rules':
            await self._process_vmalert_sync_rules(job_id, ref_id, payload)
        elif job_type == 'vmalert_regen_scrapes':
            await self._process_vmalert_regen_scrapes(job_id, ref_id, payload)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    async def start(self):
        """Arranca el loop de polling y garantiza vmalert always-on para los
        tenants de control interno (spec 011 §4.7)."""
        await super().start()
        try:
            await self._bootstrap_internal()
        except Exception as e:
            logger.error("Bootstrap de tenants internos falló: %s", e, exc_info=True)

    async def _bootstrap_internal(self):
        """Asegura que cada tenant de control interno tenga su vmalert desplegado
        (siempre-on). Idempotente: no re-encola si ya hay instancia 'deployed' o
        un job vmalert_deploy queued/running. El auto-placement usa la misma regla
        de menor carga que tenant_worker (spec 011 §4.2)."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """SELECT id FROM tenants
                   WHERE is_internal = TRUE AND status = 'active'"""
            )
            internal_ids = [r[0] for r in cursor.fetchall()]
            for tenant_id in internal_ids:
                cursor.execute(
                    """SELECT 1 FROM tenant_vmalert_instances
                       WHERE tenant_id = %s AND status = 'deployed'""",
                    (tenant_id,)
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    """SELECT 1 FROM job_state
                       WHERE type = 'vmalert_deploy' AND ref_id = %s
                         AND status IN ('queued', 'running')""",
                    (tenant_id,)
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    """SELECT id FROM infrastructure_nodes
                       WHERE component_type = 'vmalert'
                         AND is_active = TRUE AND status = 'operational'
                         AND tenants_count_active < capacity_slots
                       ORDER BY tenants_count_active ASC, id ASC
                       LIMIT 1"""
                )
                node = cursor.fetchone()
                node_id = node[0] if node else None
                cursor.execute(
                    """UPDATE tenants
                       SET has_alerts = TRUE, placement_mode = 'auto',
                           vmalert_node_id = COALESCE(vmalert_node_id, %s)
                       WHERE id = %s""",
                    (node_id, tenant_id)
                )
                await self._enqueue_job(cursor, 'vmalert_deploy', tenant_id)
                logger.info("Bootstrap interno: encolado vmalert_deploy para tenant %s", tenant_id)
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    async def _enqueue_job(self, cursor, job_type: str, ref_id: int):
        """Encola un job nuevo en job_state."""
        job_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO job_state (id, type, ref_id, status, phase, progress_pct, created_by)
               VALUES (%s, %s, %s, 'queued', 'init', 0, NULL)""",
            (job_id, job_type, ref_id)
        )

    async def _process_vmalert_deploy(self, job_id: str, tenant_id: int, payload: dict):
        """Deploy vmalert instance for tenant."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 10, "preparing")

            # Get tenant details
            cursor.execute(
                """SELECT id, name, slug, vmalert_node_id, vmalert_port, has_alerts, org_id_upper, is_internal
                   FROM tenants WHERE id=%s""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found")

            t_id, name, slug, vmalert_node_id, vmalert_port, has_alerts, org_id_upper, is_internal = row

            if not has_alerts:
                logger.info("Tenant %s has has_alerts=false, skipping vmalert deploy", tenant_id)
                return

            if not vmalert_node_id:
                raise ValueError(f"Tenant {tenant_id} has no vmalert_node_id assigned")

            await self._update_progress(job_id, 20, "allocating_port")

            # Allocate port from node's pool (spec 011 §4.7): el pool por-tenant
            # arranca en 8881; el 8880 está reservado para la unit single
            # (anomalia-vmalert.service), así que un valor previo con ese puerto
            # se reasigna en lugar de heredarse.
            if not vmalert_port or vmalert_port == 8880:
                vmalert_port = await self._allocate_vmalert_port(cursor, vmalert_node_id)
                cursor.execute(
                    "UPDATE tenants SET vmalert_port=%s WHERE id=%s",
                    (vmalert_port, tenant_id)
                )
                conn.commit()

            await self._update_progress(job_id, 40, "preparing_ansible")

            # Get node details
            cursor.execute(
                """SELECT hostname, ip_address, service_ip, admin_username, admin_password
                   FROM infrastructure_nodes WHERE id=%s""",
                (vmalert_node_id,)
            )
            node_row = cursor.fetchone()
            if not node_row:
                raise ValueError(f"Node {vmalert_node_id} not found")

            hostname, ip_address, service_ip, admin_user, admin_pass = node_row
            target_ip = service_ip or ip_address

            # Get Alertmanager URL (from alertmanager node)
            alertmanager_url = await self._get_alertmanager_url(cursor)
            # Get VictoriaMetrics select/insert URLs (from cluster nodes)
            datasource_url = await self._get_component_url(cursor, 'vmselect', 8401)
            remote_write_url = await self._get_component_url(cursor, 'vminsert', 8400)

            await self._update_progress(job_id, 60, "running_ansible")

            # La BD es la fuente de verdad de las reglas: si ya existe una versión
            # del tenant (redeploy), se conserva y se materializa al nodo en el
            # playbook; si es el primer deploy, se usa la plantilla por defecto.
            cursor.execute(
                "SELECT rules_yaml FROM tenant_vmalert_instances WHERE tenant_id = %s;",
                (tenant_id,)
            )
            prev = cursor.fetchone()
            existing_rules = prev[0] if prev else None

            # spec 011 §4.7: para tenants de control interno la regla canónica
            # (internal_rules/<slug>.yaml) se sobre-escribe en cada deploy; como
            # el PUT de reglas está bloqueado, ese archivo es el único origen
            # admisible -> las reglas internas son inmutables por construcción.
            rules_yaml = existing_rules
            if is_internal:
                rules_yaml = INTERNAL_RULES.get(slug) or existing_rules

            # Prepare vmalert_instances for Ansible. El rules_yaml NO viaja dentro
            # de esta lista: Ansible templa recursivamente la variable en los
            # `when` del playbook (ej. install-binaries.yml) y un {{ $labels.job }}
            # anidado reventaba con 'unexpected char $' (spec 011 §4.7). Las
            # reglas van por el canal aparte vmalert_rules y se materializan a
            # archivos temporales (rutas en vmalert_rules_files).
            vmalert_instance = {
                'tenant_slug': slug,
                'tenant_name': name,
                'tenant_id': t_id,
                'org_id_upper': org_id_upper,
                'is_internal': is_internal,
                'port': vmalert_port,
                'rules_path': f'/etc/anomalia/vmalert/{slug}',
                'alertmanager_url': alertmanager_url,
                'datasource_url': datasource_url,
                'remote_write_url': remote_write_url,
            }
            vmalert_instances = [vmalert_instance]

            vmalert_rules = []
            if rules_yaml is not None:
                vmalert_rules = [{
                    'tenant_slug': slug,
                    'rules_yaml': rules_yaml,
                    'rules_path': f'/etc/anomalia/vmalert/{slug}',
                }]

            # Run Ansible playbook
            await self._run_ansible_vmalert(
                job_id, target_ip, admin_user, admin_pass, vmalert_instances,
                vmalert_rules=vmalert_rules,
            )

            await self._update_progress(job_id, 90, "registering_instance")

            # Register instance
            cursor.execute(
                """INSERT INTO tenant_vmalert_instances
                       (tenant_id, instance_id, port, status, unit_name, rules_path, rules_yaml)
                   VALUES (%s, %s, %s, 'deployed', %s, %s, %s)
                   ON CONFLICT (tenant_id) DO UPDATE SET
                       instance_id = EXCLUDED.instance_id,
                       port = EXCLUDED.port,
                       status = 'deployed',
                       unit_name = EXCLUDED.unit_name,
                       rules_path = EXCLUDED.rules_path,
                       rules_yaml = EXCLUDED.rules_yaml""",
                (
                    tenant_id,
                    vmalert_node_id,
                    vmalert_port,
                    f"anomalia-vmalert-{slug}.service",
                    f"/etc/anomalia/vmalert/{slug}",
                    rules_yaml,
                )
            )

            # Increment node tenant count
            cursor.execute(
                "UPDATE infrastructure_nodes SET tenants_count_active = tenants_count_active + 1 WHERE id=%s",
                (vmalert_node_id,)
            )

            # Regen incremental de scrapes vmagent + rutas vmauth (spec 011 §4.3/§4.4)
            await self._enqueue_regenerate_scrapes(cursor, tenant_id)

            conn.commit()
            await self._update_progress(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _process_vmalert_undeploy(self, job_id: str, tenant_id: int, payload: dict):
        """Undeploy vmalert instance for tenant."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 10, "preparing")

            # Get tenant and instance details
            cursor.execute(
                """SELECT t.id, t.name, t.slug, t.vmalert_node_id, t.vmalert_port,
                          tvi.instance_id, tvi.port
                   FROM tenants t
                   LEFT JOIN tenant_vmalert_instances tvi ON tvi.tenant_id = t.id AND tvi.status = 'deployed'
                   WHERE t.id = %s""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                logger.info("Tenant %s not found for undeploy", tenant_id)
                return

            t_id, name, slug, vmalert_node_id, vmalert_port, instance_id, instance_port = row

            if not vmalert_node_id or not instance_id:
                logger.info("No vmalert instance to undeploy for tenant %s", tenant_id)
                return

            await self._update_progress(job_id, 20, "preparing_ansible")

            # Get node details
            cursor.execute(
                """SELECT hostname, ip_address, service_ip, admin_username, admin_password
                   FROM infrastructure_nodes WHERE id=%s""",
                (vmalert_node_id,)
            )
            node_row = cursor.fetchone()
            if not node_row:
                raise ValueError(f"Node {vmalert_node_id} not found")

            hostname, ip_address, service_ip, admin_user, admin_pass = node_row
            target_ip = service_ip or ip_address
            port = instance_port or vmalert_port

            await self._update_progress(job_id, 60, "running_ansible")

            # Prepare vmalert_instances for undeploy (empty list to trigger cleanup)
            vmalert_instances = [{
                'tenant_slug': slug,
                'tenant_name': name,
                'tenant_id': t_id,
                'port': port,
                'rules_path': f'/etc/anomalia/vmalert/{slug}',
                'state': 'absent',  # Signal to remove
            }]

            # Run Ansible playbook with state=absent
            await self._run_ansible_vmalert(
                job_id, target_ip, admin_user, admin_pass, vmalert_instances,
                extra_vars={'vmalert_state': 'absent'}
            )

            await self._update_progress(job_id, 90, "cleanup_db")

            # Update instance status
            cursor.execute(
                "UPDATE tenant_vmalert_instances SET status='undeployed' WHERE tenant_id=%s AND instance_id=%s",
                (tenant_id, instance_id)
            )

            # Decrement node tenant count
            cursor.execute(
                "UPDATE infrastructure_nodes SET tenants_count_active = GREATEST(tenants_count_active - 1, 0) WHERE id=%s",
                (vmalert_node_id,)
            )

            # Regen incremental de scrapes vmagent + rutas vmauth (spec 011 §4.3/§4.4)
            await self._enqueue_regenerate_scrapes(cursor, tenant_id)

            conn.commit()
            await self._update_progress(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _process_vmalert_redeploy(self, job_id: str, tenant_id: int, payload: dict):
        """Redeploy: undeploy then deploy."""
        await self._process_vmalert_undeploy(job_id, tenant_id, payload)
        await self._process_vmalert_deploy(job_id, tenant_id, payload)

    async def _process_vmalert_reload(self, job_id: str, tenant_id: int, payload: dict):
        """Reload vmalert instance via HTTP /-/reload (spec 011: timeout + healthcheck + retry)."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 20, "resolving_instance")

            cursor.execute(
                """SELECT tvi.port, n.service_ip, n.ip_address
                   FROM tenant_vmalert_instances tvi
                   JOIN infrastructure_nodes n ON n.id = tvi.instance_id
                   WHERE tvi.tenant_id = %s AND tvi.status = 'deployed'""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"No deployed vmalert instance for tenant {tenant_id}")

            port, service_ip, ip_address = row
            base_url = f"http://{service_ip or ip_address}:{port}"

            await self._update_progress(job_id, 60, "reloading")

            await self._http_reload_vmalert(base_url)

            await self._update_progress(job_id, 100, "done")
        finally:
            cursor.close()
            conn.close()

    async def _process_vmalert_sync_rules(self, job_id: str, tenant_id: int, payload: dict):
        """Materializa rules_yaml (BD = fuente de verdad) hacia el nodo y recarga vmalert."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 10, "preparing")

            cursor.execute(
                """SELECT t.slug, t.name, tvi.rules_yaml, tvi.port,
                          n.service_ip, n.ip_address, n.admin_username, n.admin_password
                   FROM tenants t
                   JOIN tenant_vmalert_instances tvi ON tvi.tenant_id = t.id AND tvi.status = 'deployed'
                   JOIN infrastructure_nodes n ON n.id = tvi.instance_id
                   WHERE t.id = %s""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"No deployed vmalert instance for tenant {tenant_id}")
            if row[2] is None:
                raise ValueError(
                    f"El tenant {tenant_id} no tiene reglas guardadas en la BD. "
                    "Guarde las reglas antes de sincronizar."
                )

            slug, name, rules_yaml, port, service_ip, ip_address, admin_user, admin_pass = row
            target_ip = service_ip or ip_address

            await self._update_progress(job_id, 30, "running_ansible")

            instances = [{
                'tenant_slug': slug,
                'tenant_name': name,
                'tenant_id': tenant_id,
                'port': port,
                'rules_path': f'/etc/anomalia/vmalert/{slug}',
                'alertmanager_url': await self._get_alertmanager_url(cursor),
                'datasource_url': await self._get_component_url(cursor, 'vmselect', 8401),
                'remote_write_url': await self._get_component_url(cursor, 'vminsert', 8400),
            }]

            # Mismo canal separado que el deploy: el rules_yaml no se serializa
            # dentro de vmalert_instances (spec 011 §4.7).
            vmalert_rules = [{
                'tenant_slug': slug,
                'rules_yaml': rules_yaml,
                'rules_path': f'/etc/anomalia/vmalert/{slug}',
            }]

            await self._run_ansible_vmalert(
                job_id, target_ip, admin_user, admin_pass, instances,
                vmalert_rules=vmalert_rules,
                playbook="sync-vmalert-rules.yml"
            )

            await self._update_progress(job_id, 70, "reloading")

            await self._http_reload_vmalert(f"http://{target_ip}:{port}")

            await self._update_progress(job_id, 100, "done")
        finally:
            cursor.close()
            conn.close()

    async def _enqueue_regenerate_scrapes(self, cursor, ref_id: int):
        """Encola un job vmalert_regen_scrapes (spec 011 §4.3/§4.4).

        La regeneración es global (refleja el conjunto completo de instancias
        vmalert por tenant), por eso ref_id solo identifica al actor que la
        disparó. El job no re-encola nada: la cadena termina naturalmente.
        """
        cursor.execute(
            """INSERT INTO job_state (id, type, ref_id, status, phase, progress_pct, created_by)
               VALUES (%s, %s, %s, 'queued', 'init', 0, %s);""",
            (str(uuid.uuid4()), 'vmalert_regen_scrapes', ref_id, None)
        )

    async def _process_vmalert_regen_scrapes(self, job_id: str, ref_id: int, payload: dict):
        """Regenera scrapes de vmagent y rutas de vmauth tras deploy/undeploy por tenant.

        La BD es la fuente de verdad (spec 005): los targets base y los jobs
        por-tenant se calculan a partir de infrastructure_nodes y
        tenant_vmalert_instances, y se inyectan al playbook sync-scrapes.yml
        como extra-vars (modo dirigido, sin inventario con grupos).
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 10, "collecting_infra")

            cursor.execute(
                """SELECT component_type, service_ip, ip_address, port,
                          admin_username, admin_password
                   FROM infrastructure_nodes
                   WHERE is_active = TRUE AND status = 'operational'
                   ORDER BY id ASC"""
            )
            infra_components = []
            vmagent_node = None
            vmauth_node = None
            for comp_type, service_ip, ip_address, port, admin_user, admin_pass in cursor.fetchall():
                component = {
                    'component': comp_type,
                    'ip': service_ip or ip_address,
                    'port': port or PORT_DEFAULTS.get(comp_type, 8427),
                    'admin_user': admin_user,
                    'admin_pass': admin_pass,
                    'target_ip': service_ip or ip_address,
                }
                infra_components.append(component)
                if comp_type == 'vmagent':
                    vmagent_node = component
                elif comp_type == 'vmauth':
                    vmauth_node = component

            if not infra_components:
                raise ValueError("No operational infra components found to regenerate scrapes")

            await self._update_progress(job_id, 30, "collecting_tenants")

            cursor.execute(
                """SELECT t.slug, t.name, t.org_id_upper, tvi.port,
                          n.service_ip, n.ip_address, tvi.instance_id, t.id
                   FROM tenant_vmalert_instances tvi
                   JOIN tenants t ON t.id = tvi.tenant_id AND t.status = 'active'
                   JOIN infrastructure_nodes n ON n.id = tvi.instance_id
                   WHERE tvi.status = 'deployed'"""
            )
            vmalert_instances = [
                {
                    'tenant_slug': slug,
                    'tenant_name': name,
                    'org_id_upper': org_id_upper,
                    'port': port,
                    'node_ip': service_ip or ip_address,
                    'instance_id': instance_id,
                    'tenant_id': tenant_id,
                }
                for slug, name, org_id_upper, port, service_ip, ip_address, instance_id, tenant_id in cursor.fetchall()
            ]

            base_ev = {
                'infra_components': infra_components,
                'vmalert_instances': vmalert_instances,
            }

            await self._update_progress(job_id, 50, "running_ansible")

            if vmagent_node is not None:
                vmauth_url = await self._get_component_url(cursor, 'vmauth', PORT_DEFAULTS['vmauth'])
                ev = dict(base_ev)
                ev.update({
                    'regen_components': ['vmagent'],
                    'vmagent_remote_write_url': (
                        f"{vmauth_url.rstrip('/')}/insert/prometheus/api/v1/write?tenant=METRICS"
                    ),
                    'vmagent_ip': vmagent_node['ip'],
                    'vmagent_port': vmagent_node['port'],
                })
                await self._run_ansible_vmalert(
                    job_id, vmagent_node['target_ip'], vmagent_node['admin_user'],
                    vmagent_node['admin_pass'], [], extra_vars=ev,
                    playbook="sync-scrapes.yml",
                )

            if vmauth_node is not None:
                ev = dict(base_ev)
                ev.update({
                    'regen_components': ['vmauth'],
                    'vmauth_ip': vmauth_node['ip'],
                    'vmauth_server_port': vmauth_node['port'],
                })
                await self._run_ansible_vmalert(
                    job_id, vmauth_node['target_ip'], vmauth_node['admin_user'],
                    vmauth_node['admin_pass'], [], extra_vars=ev,
                    playbook="sync-scrapes.yml",
                )

            await self._update_progress(job_id, 100, "done")
        finally:
            cursor.close()
            conn.close()

    async def _http_reload_vmalert(self, base_url: str):
        """Healthcheck + POST /-/reload con reintentos y backoff (spec 011)."""
        last_error: Optional[Exception] = None
        for attempt in range(1, RELOAD_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=RELOAD_TIMEOUT_SECONDS) as client:
                    health = await client.get(f"{base_url}/-/health")
                    health.raise_for_status()
                    response = await client.post(f"{base_url}/-/reload")
                    response.raise_for_status()
                last_error = None
                break
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                logger.warning(
                    "vmalert reload attempt %s/%s failed for %s: %s",
                    attempt, RELOAD_ATTEMPTS, base_url, e
                )
                if attempt < RELOAD_ATTEMPTS:
                    await asyncio.sleep(2 * attempt)

        if last_error is not None:
            raise RuntimeError(f"vmalert reload failed after {RELOAD_ATTEMPTS} attempts: {last_error}")

    async def _allocate_vmalert_port(self, cursor, node_id: int) -> int:
        """Allocate next available port from node's ports_pool.

        El pool por-tenant arranca en 8881 (spec 011 §4.7): el 8880 está
        reservado para la unit single `anomalia-vmalert.service`.
        """
        cursor.execute(
            "SELECT ports_pool FROM infrastructure_nodes WHERE id=%s",
            (node_id,)
        )
        row = cursor.fetchone()
        ports_pool = row[0] if row and row[0] else list(range(8881, 8980))

        # Find first unused port
        cursor.execute(
            "SELECT port FROM tenant_vmalert_instances WHERE instance_id=%s AND status='deployed'",
            (node_id,)
        )
        used_ports = {r[0] for r in cursor.fetchall()}

        for port in ports_pool:
            if port not in used_ports:
                return port

        # Fallback: max used + 1 (siempre >= 8882 porque 8881 ya está usado)
        return max(used_ports) + 1

    async def _get_alertmanager_url(self, cursor) -> str:
        """Get Alertmanager URL from infrastructure."""
        cursor.execute(
            """SELECT service_ip, ip_address, port
               FROM infrastructure_nodes
               WHERE component_type = 'alertmanager'
                 AND is_active = TRUE
                 AND status = 'operational'
               LIMIT 1"""
        )
        row = cursor.fetchone()
        if row:
            service_ip, ip_address, port = row
            return f"http://{service_ip or ip_address}:{port or 9093}"
        return "http://127.0.0.1:9093"

    async def _get_component_url(self, cursor, component_type: str, default_port: int) -> str:
        """Get base URL for an infra component from infrastructure_nodes (spec 005).

        Fuente de verdad = BD: devuelve la URL del primer nodo operativo de
        'component_type'; si no existe, cae a http://127.0.0.1:{default_port}.
        """
        cursor.execute(
            """SELECT service_ip, ip_address, port
               FROM infrastructure_nodes
               WHERE component_type = %s
                 AND is_active = TRUE
                 AND status = 'operational'
               LIMIT 1""",
            (component_type,)
        )
        row = cursor.fetchone()
        if row:
            service_ip, ip_address, port = row
            return f"http://{service_ip or ip_address}:{port or default_port}"
        return f"http://127.0.0.1:{default_port}"

    async def _run_ansible_vmalert(self, job_id: str, target_ip: str, admin_user: str, admin_pass: Optional[str],
                                    vmalert_instances: list, extra_vars: dict = None,
                                    vmalert_rules: Optional[list] = None,
                                    playbook: str = "install-binaries.yml"):
        """Run Ansible playbook to deploy/undeploy/sync vmalert.

        ``vmalert_instances`` es lo que viaja en los extra-vars al playbook. Las
        reglas (``vmalert_rules``) NO van ahí: contiene ``{{ ... }}`` propio de
        PromQL/vmalert y Ansible las templaria al evaluar cualquier ``when`` que
        referencie la variable (spec 011 §4.7). Se materializan a archivos
        temporales y los extra-vars solo llevan las rutas.
        """
        playbook_path = f"/app/playbooks/{playbook}"
        if not os.path.isfile(playbook_path):
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        # Prepare extra vars
        ev = {
            'ansible_user': admin_user,
            'servicio': 'vmalert',
            'gestionar_servicios': True,
            'vmalert_instances': vmalert_instances,
        }
        if extra_vars:
            ev.update(extra_vars)
        if admin_pass:
            ev['ansible_password'] = admin_pass
            ev['ansible_become_password'] = admin_pass

        # Write extra vars to temp file (secure)
        secret_dir = tempfile.mkdtemp(prefix="anomalia-ansible-vmalert-")
        extra_vars_path = os.path.join(secret_dir, "extra-vars.json")
        try:
            # Materializar reglas guardadas en la BD a archivos temporales.
            # NO se usa copy.content en los playbooks: prometheus templating con
            # {{ ... }} (labels de alerta) sería evaluado por Jinja y corrupto.
            rule_files = []
            for rule in (vmalert_rules or []):
                rules_yaml = rule.get('rules_yaml')
                if rules_yaml is not None:
                    rule_src = os.path.join(secret_dir, f"rules-{rule.get('tenant_slug', 'tenant')}.yml")
                    fd = os.open(rule_src, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as rf:
                        rf.write(rules_yaml)
                    rule_files.append({
                        'src': rule_src,
                        'dest': os.path.join(rule['rules_path'], 'alert_rules.yml'),
                        'rules_path': rule['rules_path'],
                    })
            if rule_files:
                ev['vmalert_rules_files'] = rule_files

            fd = os.open(extra_vars_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(ev, f)

            cmd = [
                "ansible-playbook",
                "-i", f"{target_ip},",
                playbook_path,
                "--extra-vars", f"@{extra_vars_path}",
            ]

            logger.info("Running vmalert playbook for job %s on %s", job_id, target_ip)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd="/app/playbooks",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError("vmalert playbook timeout (300s)")

            if proc.returncode != 0:
                error_msg = f"STDOUT:\n{stdout.decode()}\n\nSTDERR:\n{stderr.decode()}"
                raise RuntimeError(f"vmalert playbook failed: {error_msg}")

            logger.info("vmalert playbook completed for job %s", job_id)

        finally:
            # Cleanup temp files (extra vars + reglas materializadas)
            try:
                shutil.rmtree(secret_dir, ignore_errors=True)
            except Exception:
                pass

    async def _update_progress(self, job_id: str, progress: int, phase: str):
        """Update job progress."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE job_state SET progress_pct=%s, phase=%s WHERE id=%s",
                (progress, phase, job_id)
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()