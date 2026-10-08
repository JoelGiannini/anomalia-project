"""Tenant worker: processes tenant_create, tenant_delete and parses_provision jobs."""
import asyncio
import logging
import uuid
from typing import Optional

from .base import BaseWorker
from ..database import get_db_connection
from ..parses_provisioner import provision_user_parses

logger = logging.getLogger("anomalia.workers.tenant")


class TenantWorker(BaseWorker):
    """Worker that handles tenant provisioning jobs."""

    def __init__(self, interval: int = 30):
        super().__init__(interval, job_types=['tenant_create', 'tenant_delete', 'parses_provision'])

    async def process_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        if job_type == 'tenant_create':
            await self._process_tenant_create(job_id, ref_id, payload)
        elif job_type == 'tenant_delete':
            await self._process_tenant_delete(job_id, ref_id, payload)
        elif job_type == 'parses_provision':
            await self._process_parses_provision(job_id, ref_id, payload)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    async def _process_tenant_create(self, job_id: str, tenant_id: int, payload: dict):
        """Process tenant creation: assign IDs, seed datasources, enqueue dependent jobs.

        Corre completo en thread (spec 011 §4.2): sin DB síncrona ni transacciones
        abiertas en el event loop de uvicorn.
        """
        await asyncio.to_thread(self._tenant_create_sync, job_id, tenant_id)

    def _tenant_create_sync(self, job_id: str, tenant_id: int) -> None:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Get tenant details
            cursor.execute(
                """SELECT id, name, slug, type, account_id, project_id, has_alerts,
                          placement_mode, vmalert_node_id, vmalert_port, environment, org_id_upper
                   FROM tenants WHERE id=%s""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found")

            t_id, name, slug, t_type, account_id, project_id, has_alerts, placement_mode, vmalert_node_id, vmalert_port, environment, org_id_upper = row

            is_profiles = (t_type == 'profiles')

            # Update progress
            self._update_progress_sync(job_id, 20, "assigning_ids")

            # 1. Auto-generate account_id / project_id using sequences. Los tenants
            #    pyroscope (type='profiles') quedan NULL: sus perfiles no viven en
            #    un proyecto de VM cluster y su aislamiento es por header
            #    X-Scope-OrgID (spec 008), igual que el seed interno.
            if not is_profiles:
                if account_id is None:
                    cursor.execute("SELECT nextval('tenant_account_id_seq')")
                    account_id = cursor.fetchone()[0]
                if project_id is None:
                    cursor.execute("SELECT nextval('tenant_project_id_seq')")
                    project_id = cursor.fetchone()[0]

            if account_id is not None or project_id is not None:
                cursor.execute(
                    "UPDATE tenants SET account_id=%s, project_id=%s WHERE id=%s",
                    (account_id, project_id, tenant_id)
                )
                conn.commit()

            self._update_progress_sync(job_id, 40, "seeding_datasources")

            # 2. Seed tenant_datasources (idempotent)
            if is_profiles:
                self._seed_pyroscope_datasource(cursor, tenant_id, org_id_upper)
            else:
                self._seed_tenant_datasources(cursor, tenant_id, t_type, account_id, project_id)
            conn.commit()

            self._update_progress_sync(job_id, 60, "auto_placement")

            # 3. Auto placement for vmalert if needed (no aplica a pyroscope)
            if not is_profiles and placement_mode == 'auto' and vmalert_node_id is None:
                vmalert_node_id = self._select_vmalert_node_auto(cursor, environment)
                if vmalert_node_id:
                    cursor.execute(
                        "UPDATE tenants SET vmalert_node_id=%s WHERE id=%s",
                        (vmalert_node_id, tenant_id)
                    )
                    conn.commit()

            self._update_progress_sync(job_id, 80, "enqueue_dependent")

            # 4. Enqueue dependent jobs. Los tenants pyroscope no obtienen vmalert
            #    (los perfiles no son PromQL consultables por vmalert, spec 011 §4.6).
            if has_alerts and not is_profiles:
                self._enqueue_job(cursor, 'vmalert_deploy', tenant_id)
            self._enqueue_job(cursor, 'parses_provision', tenant_id)
            conn.commit()

            # 5. Mark tenant active
            cursor.execute(
                "UPDATE tenants SET status='active' WHERE id=%s",
                (tenant_id,)
            )
            conn.commit()

            self._update_progress_sync(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _process_tenant_delete(self, job_id: str, tenant_id: int, payload: dict):
        """Process tenant deletion: cleanup resources.

        Corre completo en thread (spec 011 §4.2).
        """
        await asyncio.to_thread(self._tenant_delete_sync, job_id, tenant_id)

    def _tenant_delete_sync(self, job_id: str, tenant_id: int) -> None:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            self._update_progress_sync(job_id, 20, "cleanup_start")

            # Mark tenant as deleting
            cursor.execute(
                "UPDATE tenants SET status='deleting' WHERE id=%s",
                (tenant_id,)
            )
            conn.commit()

            # Enqueue vmalert_undeploy si has alerts (no aplica a pyroscope: no tiene vmalert)
            cursor.execute("SELECT has_alerts, type FROM tenants WHERE id=%s", (tenant_id,))
            row = cursor.fetchone()
            if row and row[0] and row[1] != 'profiles':
                self._enqueue_job(cursor, 'vmalert_undeploy', tenant_id)

            # Cleanup tenant_datasources, user_tenants, role_tenants, etc.
            cursor.execute("DELETE FROM tenant_datasources WHERE tenant_id=%s", (tenant_id,))
            cursor.execute("DELETE FROM user_tenants WHERE tenant_id=%s", (tenant_id,))
            cursor.execute("DELETE FROM role_tenants WHERE tenant_id=%s", (tenant_id,))

            # Mark tenant as deleted_cleanup
            cursor.execute(
                "UPDATE tenants SET status='deleted_cleanup', deleted_at=NOW() WHERE id=%s",
                (tenant_id,)
            )
            conn.commit()

            self._update_progress_sync(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _process_parses_provision(self, job_id: str, tenant_id: int, payload: dict):
        """Provision Parses for every user with access to the tenant (idempotent, spec 011 §3.6)."""
        await self._update_progress(job_id, 20, "collecting_users")

        usernames = await asyncio.to_thread(self._parses_collect_users, tenant_id)

        if not usernames:
            logger.info("parses_provision: no active users for tenant %s", tenant_id)
            await self._update_progress(job_id, 100, "done")
            return

        await self._update_progress(job_id, 60, "provisioning_parses")

        errors: list[str] = []
        for username in usernames:
            try:
                await asyncio.to_thread(provision_user_parses, username)
            except Exception as e:
                logger.error("parses_provision failed for user %s (tenant %s): %s", username, tenant_id, e)
                errors.append(f"{username}: {e}")

        if errors:
            raise RuntimeError(f"parses_provision partial failure: {'; '.join(errors)[:200]}")

        await self._update_progress(job_id, 100, "done")

    @staticmethod
    def _parses_collect_users(tenant_id: int) -> list[str]:
        """Fase de lectura en thread: usuarios con acceso al tenant (spec 011 §4.2)."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """SELECT DISTINCT u.username
                   FROM users u
                   JOIN user_tenants ut ON ut.user_id = u.id
                   WHERE ut.tenant_id = %s AND u.is_active = TRUE""",
                (tenant_id,)
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

    def _seed_tenant_datasources(self, cursor, tenant_id: int, t_type: str, account_id: int, project_id: int):
        """Seed tenant_datasources based on infrastructure select nodes."""
        cursor.execute(
            """SELECT id, component_type, service_ip, ip_address, port
               FROM infrastructure_nodes
               WHERE component_type IN ('vmselect', 'vlselect', 'vtselect')
                 AND is_active = TRUE
                 AND status = 'operational'"""
        )
        select_nodes = cursor.fetchall()

        for node_id, comp_type, service_ip, ip_address, port in select_nodes:
            kind = self._component_to_kind(comp_type)
            read_url = f"http://{service_ip or ip_address}:{port}"
            scoping = 'path' if kind == 'VictoriaMetrics' else 'header'

            cursor.execute(
                """INSERT INTO tenant_datasources (tenant_id, kind, read_url, scoping, account_id, project_id, enabled)
                   VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                   ON CONFLICT (tenant_id) DO UPDATE SET
                       kind = EXCLUDED.kind,
                       read_url = EXCLUDED.read_url,
                       scoping = EXCLUDED.scoping,
                       account_id = EXCLUDED.account_id,
                       project_id = EXCLUDED.project_id,
                       enabled = EXCLUDED.enabled""",
                (tenant_id, kind, read_url, scoping, account_id, project_id)
            )

    def _component_to_kind(self, comp_type: str) -> str:
        mapping = {
            'vmselect': 'VictoriaMetrics',
            'vlselect': 'VictoriaLogs',
            'vtselect': 'VictoriaTraces',
        }
        return mapping.get(comp_type, 'VictoriaMetrics')

    def _seed_pyroscope_datasource(self, cursor, tenant_id: int, org_id_upper: Optional[str]):
        """Seed datasource Pyroscope para tenants type='profiles' (spec 008 §2).

        El read_url apunta a la base del nodo Pyroscope y el aislamiento es por
        header `X-Scope-OrgID` (org_id), sin account/project (los perfiles no son
        series PromQL consultables vía vmselect). Mismo shape que el seed interno
        de init.sql.j2: kind='Pyroscope', scoping='header', org_id=<org upper>.
        """
        cursor.execute(
            """SELECT service_ip, ip_address, port
               FROM infrastructure_nodes
               WHERE component_type = 'pyroscope'
                 AND is_active = TRUE
                 AND status = 'operational'
               LIMIT 1"""
        )
        row = cursor.fetchone()
        if row:
            service_ip, ip_address, port = row
            base_url = f"http://{service_ip or ip_address}:{port or 4040}"
        else:
            base_url = "http://127.0.0.1:4040"
        cursor.execute(
            """INSERT INTO tenant_datasources (tenant_id, kind, read_url, scoping, account_id, project_id, org_id, enabled)
               VALUES (%s, 'Pyroscope', %s, 'header', NULL, NULL, %s, TRUE)
               ON CONFLICT (tenant_id) DO UPDATE SET
                   kind = EXCLUDED.kind,
                   read_url = EXCLUDED.read_url,
                   scoping = EXCLUDED.scoping,
                   account_id = EXCLUDED.account_id,
                   project_id = EXCLUDED.project_id,
                   org_id = EXCLUDED.org_id,
                   enabled = EXCLUDED.enabled""",
            (tenant_id, base_url, org_id_upper)
        )

    def _select_vmalert_node_auto(self, cursor, environment: Optional[str] = None) -> Optional[int]:
        """Select vmalert node with least tenants (auto placement)."""
        cursor.execute(
            """SELECT id, tenants_count_active, capacity_slots
               FROM infrastructure_nodes
               WHERE component_type = 'vmalert'
                 AND is_active = TRUE
                 AND status = 'operational'
                 AND tenants_count_active < capacity_slots
               ORDER BY tenants_count_active ASC, id ASC
               LIMIT 1"""
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def _enqueue_job(self, cursor, job_type: str, ref_id: int) -> str:
        """Enqueue a new job in job_state (sync: fases en thread, spec 011 §4.2)."""
        job_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO job_state (id, type, ref_id, status, phase, progress_pct, created_by)
               VALUES (%s, %s, %s, 'queued', 'init', 0, NULL)""",
            (job_id, job_type, ref_id)
        )
        return job_id

    async def _update_progress(self, job_id: str, progress: int, phase: str):
        """Update job progress (en thread: nunca bloquea el event loop)."""
        await asyncio.to_thread(self._update_progress_sync, job_id, progress, phase)

    @staticmethod
    def _update_progress_sync(job_id: str, progress: int, phase: str):
        """UPDATE de progreso en transacción corta (spec 011 §4.2)."""
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