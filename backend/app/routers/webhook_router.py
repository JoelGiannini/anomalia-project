"""Webhook endpoints for Alertmanager and external integrations."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime
import json
import logging

from ..auth import verify_any_user_token, verify_admin_token
from ..database import get_db_connection
from ..ai_providers import get_provider, AIProviderError, build_alert_prompt

router = APIRouter(prefix="/api/v1/webhook", tags=["Webhooks"])

logger = logging.getLogger(__name__)


class AlertmanagerAlert(BaseModel):
    status: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    startsAt: str
    endsAt: str
    generatorURL: str
    fingerprint: str


class AlertmanagerPayload(BaseModel):
    version: str
    groupKey: str
    status: str
    receiver: str
    groupLabels: Dict[str, str]
    commonLabels: Dict[str, str]
    commonAnnotations: Dict[str, str]
    externalURL: str
    alerts: List[Dict[str, Any]]


def _enrich_and_persist_alerts(alerts: List[Dict[str, Any]], status: str) -> List[Dict[str, Any]]:
    """Enriquecimiento IA + persistencia en alert_history (transacción corta).

    Sync: se ejecuta vía asyncio.to_thread para que ni la llamada a la IA ni una
    espera de lock congele el event loop de uvicorn (spec 011 §4.2).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        enriched_alerts = []

        for alert in alerts:
            # Enriquecer con IA
            ai_analysis = None
            try:
                provider = get_provider()
                prompt = build_alert_prompt(alert)
                ai_analysis = provider.generate(prompt)
            except Exception as e:
                logger.warning(f"AI enrichment failed for alert {alert.get('fingerprint')}: {e}")
                ai_analysis = f"Error en enriquecimiento IA: {str(e)}"

            # Persistir en alert_history
            cursor.execute(
                """INSERT INTO alert_history 
                   (alertname, severity, summary, description, ai_analysis, status, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (alertname, severity, summary, description) DO NOTHING""",
                (
                    alert.get("labels", {}).get("alertname", "unknown"),
                    alert.get("labels", {}).get("severity", "unknown"),
                    alert.get("annotations", {}).get("summary", ""),
                    alert.get("annotations", {}).get("description", ""),
                    ai_analysis,
                    status,  # firing | resolved
                    datetime.utcnow(),
                )
            )

            enriched_alerts.append({
                "fingerprint": alert.get("fingerprint"),
                "status": status,
                "ai_analysis": ai_analysis,
            })

        conn.commit()
        return enriched_alerts
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@router.post("/alertmanager")
async def alertmanager_webhook(
    payload: AlertmanagerPayload,
    request: Request,
    admin_payload: dict = Depends(verify_admin_token)
):
    """Recibe alertas de Alertmanager, las enriquece con IA y las persiste.
    
    Espera el formato estándar de Alertmanager webhook.
    """
    try:
        enriched_alerts = await asyncio.to_thread(
            _enrich_and_persist_alerts, payload.alerts, payload.status
        )
        return {
            "status": "received",
            "alerts_processed": len(enriched_alerts),
            "enriched": enriched_alerts,
        }
    except Exception as e:
        logger.error(f"Alertmanager webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alertmanager/test")
def test_alertmanager_webhook(admin_payload: dict = Depends(verify_admin_token)):
    """Endpoint de prueba para verificar conectividad."""
    return {"status": "ok", "message": "Alertmanager webhook endpoint is reachable"}