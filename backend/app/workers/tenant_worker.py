"""Tenant worker: processes tenant_create and tenant_delete jobs."""
import logging
import uuid
from typing import Optional
from .base import BaseWorker
from ..database import get_db_connection

logger = logging.getLogger("anomalia.workers.tenant")


class TenantWorker(BaseWorker):
    """Worker that handles tenant provisioning jobs."""

    def __init__(self, interval: int = 30):
        super().__init__(interval, job_types=['tenant_create', 'tenant_delete'])

    async def process_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        if job_type == 'tenant_create':
            await self._process_tenant_create(job_id, ref_id, payload)
        elif job_type == 'tenant_delete':
            await self._process_tenant_delete(job_id, ref_id, payload)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    async def _process_tenant_create(self, job_id: str, tenant_id: int, payload: dict):
        """Process tenant creation: assign IDs, seed datasources, enqueue dependent jobs."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Get tenant details
            cursor.execute(
                """SELECT id, name, slug, type, account_id, project_id, has_alerts, 
                          placement_mode, vmalert_node_id, vmalert_port, environment
                   FROM tenants WHERE id=%s""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found")

            t_id, name, slug, t_type, account_id, project_id, has_alerts, placement_mode, vmalert_node_id, vmalert_port, environment = row

            # Update progress
            await self._update_progress(job_id, 20, "assigning_ids")

            # 1. Auto-generate account_id / project_id using sequences
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

            await self._update_progress(job_id, 40, "seeding_datasources")

            # 2. Seed tenant_datasources (idempotent)
            await self._seed_tenant_datasources(cursor, tenant_id, t_type, account_id, project_id)
            conn.commit()

            await self._update_progress(job_id, 60, "auto_placement")

            # 3. Auto placement for vmalert if needed
            if placement_mode == 'auto' and vmalert_node_id is None:
                vmalert_node_id = await self._select_vmalert_node_auto(cursor, environment)
                if vmalert_node_id:
                    cursor.execute(
                        "UPDATE tenants SET vmalert_node_id=%s WHERE id=%s",
                        (vmalert_node_id, tenant_id)
                    )
                    conn.commit()

            await self._update_progress(job_id, 80, "enqueue_dependent")

            # 4. Enqueue dependent jobs
            if has_alerts:
                await self._enqueue_job(cursor, 'vmalert_deploy', tenant_id)
            await self._enqueue_job(cursor, 'parses_provision', tenant_id)
            conn.commit()

            # 5. Mark tenant active
            cursor.execute(
                "UPDATE tenants SET status='active' WHERE id=%s",
                (tenant_id,)
            )
            conn.commit()

            await self._update_progress(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _process_tenant_delete(self, job_id: str, tenant_id: int, payload: dict):
        """Process tenant deletion: cleanup resources."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 20, "cleanup_start")

            # Mark tenant as deleting
            cursor.execute(
                "UPDATE tenants SET status='deleting' WHERE id=%s",
                (tenant_id,)
            )
            conn.commit()

            # Enqueue vmalert_undeploy if has alerts
            cursor.execute("SELECT has_alerts FROM tenants WHERE id=%s", (tenant_id,))
            row = cursor.fetchone()
            if row and row[0]:
                await self._enqueue_job(cursor, 'vmalert_undeploy', tenant_id)

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

            await self._update_progress(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _seed_tenant_datasources(self, cursor, tenant_id: int, t_type: str, account_id: int, project_id: int):
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

    async def _select_vmalert_node_auto(self, cursor, environment: Optional[str] = None) -> Optional[int]:
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

    async def _enqueue_job(self, cursor, job_type: str, ref_id: int, payload: dict = None):
        """Enqueue a new job in job_state."""
        job_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO job_state (id, type, ref_id, status, phase, progress_pct, payload, created_by)
               VALUES (%s, %s, %s, 'queued', 'init', 0, %s, NULL)""",
            (job_id, job_type, ref_id, payload or {})
        )

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