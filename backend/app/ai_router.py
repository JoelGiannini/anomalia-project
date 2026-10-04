from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import verify_admin_token
from .database import get_db_connection
from .ai_providers import (
    AI_PROVIDER_CATALOG,
    DEFAULT_AI_PROVIDER,
    DEFAULT_GEMINI_MODEL,
    AIProviderError,
    get_ai_settings,
    get_gemini_models,
    get_provider,
)

router = APIRouter(prefix="/api/v1/ai", tags=["AI Providers"])

TEST_PROMPT = "Responde únicamente con la palabra OK."


class AIConfigPayload(BaseModel):
    provider: str
    zen_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None


class AITestPayload(BaseModel):
    provider: Optional[str] = None


@router.get("/providers")
def list_ai_providers(admin_payload: dict = Depends(verify_admin_token)) -> Dict[str, Any]:
    settings = get_ai_settings()
    providers: List[Dict[str, Any]] = []
    for p in AI_PROVIDER_CATALOG:
        if p["group"] == "free":
            configured = bool(settings.get("zen_api_key"))
        elif p["group"] == "apikey":
            configured = bool(settings.get("gemini_api_key"))
        else:
            configured = True
        providers.append({**p, "configured": configured})
    return {"providers": providers}


@router.get("/config")
def get_ai_config(admin_payload: dict = Depends(verify_admin_token)) -> Dict[str, Any]:
    settings = get_ai_settings()
    catalog_ids = {p["id"] for p in AI_PROVIDER_CATALOG}
    stored = settings.get("selected_provider") or DEFAULT_AI_PROVIDER
    # Fallback: si el proveedor guardado ya no existe en el catálogo
    # (p. ej. un modelo free retirado), se expone el proveedor por defecto.
    provider = stored if stored in catalog_ids else DEFAULT_AI_PROVIDER
    return {
        "provider": provider,
        "has_zen_key": bool(settings.get("zen_api_key")),
        "has_gemini_key": bool(settings.get("gemini_api_key")),
        "gemini_model": settings.get("gemini_model") or DEFAULT_GEMINI_MODEL,
    }


@router.put("/config")
def save_ai_config(payload: AIConfigPayload, admin_payload: dict = Depends(verify_admin_token)) -> Dict[str, str]:
    catalog_ids = {p["id"] for p in AI_PROVIDER_CATALOG}
    if payload.provider not in catalog_ids:
        raise HTTPException(status_code=400, detail="Proveedor de IA desconocido.")
    gemini_model = (payload.gemini_model or "").strip() or DEFAULT_GEMINI_MODEL

    updates = ["selected_provider = %s", "gemini_model = %s", "updated_at = CURRENT_TIMESTAMP"]
    params: List[Any] = [payload.provider, gemini_model]
    if payload.zen_api_key is not None:
        updates.append("zen_api_key = %s")
        params.append(payload.zen_api_key)
    if payload.gemini_api_key is not None:
        updates.append("gemini_api_key = %s")
        params.append(payload.gemini_api_key)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM ai_settings;")
        exists = cursor.fetchone()[0] > 0
        if exists:
            cursor.execute(
                f"UPDATE ai_settings SET {', '.join(updates)} "
                "WHERE id = (SELECT id FROM ai_settings ORDER BY id LIMIT 1)",
                params,
            )
        else:
            cursor.execute(
                "INSERT INTO ai_settings (selected_provider, zen_api_key, gemini_api_key, gemini_model) "
                "VALUES (%s, %s, %s, %s)",
                (payload.provider, payload.zen_api_key or "", payload.gemini_api_key or "", gemini_model),
            )
        conn.commit()
        return {"status": "success", "message": "Configuración de IA guardada correctamente."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"No se pudo guardar la configuración: {str(e)}")
    finally:
        cursor.close()
        conn.close()


@router.post("/test")
def test_ai_provider(payload: AITestPayload, admin_payload: dict = Depends(verify_admin_token)) -> Dict[str, Any]:
    provider_id = payload.provider or None
    try:
        provider = get_provider(provider_id)
        response = provider.generate(TEST_PROMPT)
    except AIProviderError as e:
        return {"ok": False, "provider": provider_id or get_ai_settings().get("selected_provider"), "error": str(e)}
    return {"ok": True, "provider": provider_id or get_ai_settings().get("selected_provider"), "response": response}


@router.get("/gemini-models")
def list_gemini_models(admin_payload: dict = Depends(verify_admin_token)) -> Dict[str, Any]:
    settings = get_ai_settings()
    models = get_gemini_models(settings.get("gemini_api_key", ""))
    current = settings.get("gemini_model") or DEFAULT_GEMINI_MODEL
    if current not in models:
        models.insert(0, current)
    return {"models": models, "current": current}
