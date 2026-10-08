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
        jobs = await asyncio.to_thread(self._claim_jobs)
        for job_id, job_type, ref_id in jobs:
            await self._execute_job(job_id, job_type, ref_id, {})

    def _claim_jobs(self) -> list:
        """Reclama jobs queued en una transaccion corta (spec 011 4.2).

        Corre en thread (asyncio.to_thread): una espera de lock aqui no debe
        congelar el event loop de uvicorn.
        """
        if not self.job_types:
            return []
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            placeholders = ','.join(['%s'] * len(self.job_types))
            cursor.execute(
                """
                SELECT id, type, ref_id
                FROM job_state
                WHERE type IN (""" + placeholders + """)
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
            return [(j[0], j[1], j[2]) for j in jobs]
        finally:
            cursor.close()
            conn.close()

    async def _execute_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        """Execute a single job with status updates."""
        await asyncio.to_thread(self._set_job_running, job_id)
        try:
            await self.process_job(job_id, job_type, ref_id, payload)
            await asyncio.to_thread(self._set_job_succeeded, job_id)
            logger.info("Job %s (%s) completed for ref_id=%s", job_id, job_type, ref_id)
        except Exception as e:
            logger.error("Job %s (%s) failed for ref_id=%s: %s", job_id, job_type, ref_id, e, exc_info=True)
            try:
                await asyncio.to_thread(self._set_job_failed, job_id, e)
            except Exception:
                pass

    @staticmethod
    def _set_job_running(job_id: str) -> None:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE job_state SET status='running', started_at=NOW(), phase='processing', progress_pct=10 WHERE id=%s",
                    (job_id,)
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _set_job_succeeded(job_id: str) -> None:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE job_state SET status='succeeded', finished_at=NOW(), phase='done', progress_pct=100 WHERE id=%s",
                    (job_id,)
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _set_job_failed(job_id: str, error: Exception) -> None:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE job_state SET status='failed', finished_at=NOW(), phase='error', error_code=%s, logs_ref=%s WHERE id=%s",
                    (type(error).__name__[:50], str(error)[:255], job_id)
                )
            conn.commit()
        finally:
            conn.close()

    @abstractmethod
    async def process_job(self, job_id: str, job_type: str, ref_id: int, payload: dict):
        """Process a specific job type. Must be implemented by subclass."""
        pass