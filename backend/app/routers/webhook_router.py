"""Webhook endpoints for Alertmanager and external integrations."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime
import json
import logging

from .auth import verify_any_user_token, verify_admin_token
from .database import get_db_connection
from .ai_providers import get_provider, AIProviderError, build_alert_prompt

router = APIRouter(prefix="/api/v1/webhook", tags=["Webhooks"])

logger = logging.getLogger(__name__)


class AlertmanagerLabel(BaseModel):
    __root__: Dict[str, str]


class AlertmanagerAnnotation(BaseModel):
    __root__: Dict[str, str]


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


@router.post("/alertmanager")
async def alertmanager_webhook(
    payload: AlertmanagerPayload,
    request: Request,
    admin_payload: dict = Depends(verify_admin_token)
):
    """Recibe alertas de Alertmanager, las enriquece con IA y las persiste.
    
    Espera el formato estándar de Alertmanager webhook.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        enriched_alerts = []
        
        for alert in payload.alerts:
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
                    payload.status,  # firing | resolved
                    datetime.utcnow(),
                )
            )
            
            enriched_alerts.append({
                "fingerprint": alert.get("fingerprint"),
                "status": payload.status,
                "ai_analysis": ai_analysis,
            })
        
        conn.commit()
        
        return {
            "status": "received",
            "alerts_processed": len(enriched_alerts),
            "enriched": enriched_alerts,
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Alertmanager webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@router.get("/alertmanager/test")
def test_alertmanager_webhook(admin_payload: dict = Depends(verify_admin_token)):
    """Endpoint de prueba para verificar conectividad."""
    return {"status": "ok", "message": "Alertmanager webhook endpoint is reachable"}