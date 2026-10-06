"""Vmalert worker: processes vmalert_deploy, vmalert_undeploy, vmalert_redeploy jobs."""
import json
import logging
import os
import subprocess
import tempfile
from typing import Optional
from .base import BaseWorker
from ..database import get_db_connection

logger = logging.getLogger("anomalia.workers.vmalert")


class VmalertWorker(BaseWorker):
    """Worker that handles vmalert deployment jobs."""

    def __init__(self, interval: int = 30):
        super().__init__(interval, job_types=['vmalert_deploy', 'vmalert_undeploy', 'vmalert_redeploy'])

    async def process_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        if job_type == 'vmalert_deploy':
            await self._process_vmalert_deploy(job_id, ref_id, payload)
        elif job_type == 'vmalert_undeploy':
            await self._process_vmalert_undeploy(job_id, ref_id, payload)
        elif job_type == 'vmalert_redeploy':
            await self._process_vmalert_redeploy(job_id, ref_id, payload)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    async def _process_vmalert_deploy(self, job_id: str, tenant_id: int, payload: dict):
        """Deploy vmalert instance for tenant."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            await self._update_progress(job_id, 10, "preparing")

            # Get tenant details
            cursor.execute(
                """SELECT id, name, slug, vmalert_node_id, vmalert_port, has_alerts
                   FROM tenants WHERE id=%s""",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found")

            t_id, name, slug, vmalert_node_id, vmalert_port, has_alerts = row

            if not has_alerts:
                logger.info("Tenant %s has has_alerts=false, skipping vmalert deploy", tenant_id)
                return

            if not vmalert_node_id:
                raise ValueError(f"Tenant {tenant_id} has no vmalert_node_id assigned")

            await self._update_progress(job_id, 20, "allocating_port")

            # Allocate port from node's pool
            if not vmalert_port:
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

            await self._update_progress(job_id, 60, "running_ansible")

            # Prepare vmalert_instances for Ansible
            vmalert_instances = [{
                'tenant_slug': slug,
                'tenant_name': name,
                'tenant_id': t_id,
                'port': vmalert_port,
                'rules_path': f'/etc/anomalia/vmalert/{slug}',
                'alertmanager_url': alertmanager_url,
            }]

            # Run Ansible playbook
            await self._run_ansible_vmalert(
                job_id, target_ip, admin_user, admin_pass, vmalert_instances
            )

            await self._update_progress(job_id, 90, "registering_instance")

            # Register instance
            cursor.execute(
                """INSERT INTO tenant_vmalert_instances (tenant_id, instance_id, port, status)
                   VALUES (%s, %s, %s, 'deployed')
                   ON CONFLICT (tenant_id, instance_id) DO UPDATE SET
                       port = EXCLUDED.port,
                       status = 'deployed'""",
                (tenant_id, vmalert_node_id, vmalert_port)
            )

            # Increment node tenant count
            cursor.execute(
                "UPDATE infrastructure_nodes SET tenants_count_active = tenants_count_active + 1 WHERE id=%s",
                (vmalert_node_id,)
            )

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

            conn.commit()
            await self._update_progress(job_id, 100, "done")

        finally:
            cursor.close()
            conn.close()

    async def _process_vmalert_redeploy(self, job_id: str, tenant_id: int, payload: dict):
        """Redeploy: undeploy then deploy."""
        await self._process_vmalert_undeploy(job_id, tenant_id, payload)
        await self._process_vmalert_deploy(job_id, tenant_id, payload)

    async def _allocate_vmalert_port(self, cursor, node_id: int) -> int:
        """Allocate next available port from node's ports_pool."""
        cursor.execute(
            "SELECT ports_pool FROM infrastructure_nodes WHERE id=%s",
            (node_id,)
        )
        row = cursor.fetchone()
        ports_pool = row[0] if row and row[0] else list(range(8880, 8980))

        # Find first unused port
        cursor.execute(
            "SELECT port FROM tenant_vmalert_instances WHERE instance_id=%s AND status='deployed'",
            (node_id,)
        )
        used_ports = {r[0] for r in cursor.fetchall()}

        for port in ports_pool:
            if port not in used_ports:
                return port

        # Fallback: max used + 1
        return (max(used_ports) + 1) if used_ports else 8880

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

    async def _run_ansible_vmalert(self, job_id: str, target_ip: str, admin_user: str, admin_pass: Optional[str],
                                    vmalert_instances: list, extra_vars: dict = None):
        """Run Ansible playbook to deploy/undeploy vmalert."""
        playbook_path = "/app/playbooks/install-binaries.yml"
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
            # Cleanup temp file
            try:
                os.unlink(extra_vars_path)
                os.rmdir(secret_dir)
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