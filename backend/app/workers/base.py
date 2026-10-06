"""Base worker class for background job processing."""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional
from ..database import get_db_connection

logger = logging.getLogger("anomalia.workers")


class BaseWorker(ABC):
    """Base class for background workers that poll job_state table."""

    def __init__(self, interval: int = 30, job_types: list[str] = None):
        self.interval = interval
        self.job_types = job_types or []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the worker polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Worker %s started (interval=%ss, types=%s)", self.__class__.__name__, self.interval, self.job_types)

    async def stop(self):
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Worker %s stopped", self.__class__.__name__)

    async def _run_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._process_pending_jobs()
            except Exception as e:
                logger.error("Error in worker %s: %s", self.__class__.__name__, e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _process_pending_jobs(self):
        """Fetch and process pending jobs."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            placeholders = ','.join(['%s'] * len(self.job_types))
            cursor.execute(
                f"""
                SELECT id, type, ref_id
                FROM job_state
                WHERE type IN ({placeholders})
                  AND status = 'queued'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 10
                """,
                tuple(self.job_types)
            )
            jobs = cursor.fetchall()
            if jobs:
                cursor.execute(
                    """UPDATE job_state
                       SET status='running', started_at=NOW(), phase='processing', progress_pct=10
                       WHERE id = ANY(%s)""",
                    ([j[0] for j in jobs],)
                )
                conn.commit()
            for job_id, job_type, ref_id in jobs:
                await self._execute_job(job_id, job_type, ref_id, {})
        finally:
            cursor.close()
            conn.close()

    async def _execute_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        """Execute a single job with status updates."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE job_state SET status='running', started_at=NOW(), phase='processing', progress_pct=10 WHERE id=%s",
                (job_id,)
            )
            conn.commit()

            await self.process_job(job_id, job_type, ref_id, payload)

            cursor.execute(
                "UPDATE job_state SET status='succeeded', finished_at=NOW(), phase='done', progress_pct=100 WHERE id=%s",
                (job_id,)
            )
            conn.commit()
            logger.info("Job %s (%s) completed for ref_id=%s", job_id, job_type, ref_id)

        except Exception as e:
            logger.error("Job %s (%s) failed for ref_id=%s: %s", job_id, job_type, ref_id, e, exc_info=True)
            try:
                cursor.execute(
                    "UPDATE job_state SET status='failed', finished_at=NOW(), phase='error', error_code=%s, logs_ref=%s WHERE id=%s",
                    (type(e).__name__[:50], str(e)[:255], job_id)
                )
                conn.commit()
            except Exception:
                pass
        finally:
            cursor.close()
            conn.close()

    @abstractmethod
    async def process_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        """Process a specific job type. Must be implemented by subclass."""
        pass