import os
import psycopg2
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, AliasChoices, ConfigDict

from .auth import verify_admin_token

router = APIRouter(prefix="/api/v1/oidc", tags=["OIDC Providers"])

# --- CONEXIÓN A BASE DE DATOS LOCAL ---
def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        import urllib.parse as urlparse
        parsed_url = urlparse.urlparse(database_url)
        return psycopg2.connect(
            dbname=parsed_url.path[1:],
            user=parsed_url.username,
            password=parsed_url.password,
            host=parsed_url.hostname,
            port=parsed_url.port
        )
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "anomal_db"),
        user=os.getenv("DB_USER", "anomal_user"),
        password=os.getenv("DB_PASSWORD", "anomal_password")
    )

# --- MODELOS PYDANTIC TOLERANTES (Evitan el error 422) ---
class OIDCProviderCreate(BaseModel):
    name: str
    client_id: str = Field(validation_alias=AliasChoices('client_id', 'clientId'))
    issuer_url: str = Field(validation_alias=AliasChoices('issuer_url', 'issuerUrl', 'issuer'))
    client_secret: Optional[str] = Field(default="", validation_alias=AliasChoices('client_secret', 'clientSecret', 'secret'))
    redirect_uri: Optional[str] = Field(default="anomalia://callback", validation_alias=AliasChoices('redirect_uri', 'redirectUri'))
    is_active: Optional[bool] = Field(default=True, validation_alias=AliasChoices('is_active', 'isActive'))

    model_config = ConfigDict(populate_by_name=True)

class OIDCProviderUpdate(BaseModel):
    name: Optional[str] = None
    client_id: Optional[str] = Field(default=None, validation_alias=AliasChoices('client_id', 'clientId'))
    client_secret: Optional[str] = Field(default=None, validation_alias=AliasChoices('client_secret', 'clientSecret', 'secret'))
    issuer_url: Optional[str] = Field(default=None, validation_alias=AliasChoices('issuer_url', 'issuerUrl', 'issuer'))
    redirect_uri: Optional[str] = Field(default=None, validation_alias=AliasChoices('redirect_uri', 'redirectUri'))
    is_active: Optional[bool] = Field(default=None, validation_alias=AliasChoices('is_active', 'isActive'))

    model_config = ConfigDict(populate_by_name=True)

# --- ENDPOINTS ABM: OIDC PROVIDERS ---

@router.get("/providers")
@router.get("/")
def list_oidc_providers(admin_payload: dict = Depends(verify_admin_token)):
    """Lista todos los proveedores OIDC configurados (Devuelve lista directa para la app móvil)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, name, client_id, issuer_url, redirect_uri, is_active, created_at 
            FROM oidc_providers 
            ORDER BY id ASC
        """)
        providers = [
            {
                "id": r[0],
                "name": r[1],
                "client_id": r[2],
                "issuer_url": r[3],
                "redirect_uri": r[4],
                "is_active": r[5],
                "created_at": str(r[6])
            }
            for r in cursor.fetchall()
        ]
        return providers
    finally:
        cursor.close()
        conn.close()

@router.post("/", status_code=status.HTTP_201_CREATED)
@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_oidc_provider(payload: OIDCProviderCreate, admin_payload: dict = Depends(verify_admin_token)):
    """Crea un nuevo proveedor OIDC."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO oidc_providers (name, client_id, client_secret, issuer_url, redirect_uri, is_active) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            RETURNING id, name, client_id, issuer_url, redirect_uri, is_active
            """,
            (payload.name, payload.client_id, payload.client_secret, payload.issuer_url, payload.redirect_uri, payload.is_active)
        )
        new_provider = cursor.fetchone()
        conn.commit()
        return {
            "status": "success",
            "message": f"Proveedor OIDC '{payload.name}' creado correctamente.",
            "provider": {
                "id": new_provider[0],
                "name": new_provider[1],
                "client_id": new_provider[2],
                "issuer_url": new_provider[3],
                "redirect_uri": new_provider[4],
                "is_active": new_provider[5]
            }
        }
    except Exception as e:
        conn.rollback()
        print(f"ERROR DB CREATE OIDC: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error al crear proveedor: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@router.put("/{provider_id}")
@router.put("/providers/{provider_id}")
def update_oidc_provider(provider_id: int, payload: OIDCProviderUpdate, admin_payload: dict = Depends(verify_admin_token)):
    """Actualiza la configuración de un proveedor OIDC existente."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM oidc_providers WHERE id = %s", (provider_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Proveedor OIDC no encontrado.")

        fields = []
        values = []

        if payload.name is not None:
            fields.append("name = %s")
            values.append(payload.name)
        if payload.client_id is not None:
            fields.append("client_id = %s")
            values.append(payload.client_id)
        if payload.client_secret is not None:
            fields.append("client_secret = %s")
            values.append(payload.client_secret)
        if payload.issuer_url is not None:
            fields.append("issuer_url = %s")
            values.append(payload.issuer_url)
        if payload.redirect_uri is not None:
            fields.append("redirect_uri = %s")
            values.append(payload.redirect_uri)
        if payload.is_active is not None:
            fields.append("is_active = %s")
            values.append(payload.is_active)

        if fields:
            values.append(provider_id)
            query = f"UPDATE oidc_providers SET {', '.join(fields)} WHERE id = %s"
            cursor.execute(query, tuple(values))
            conn.commit()

        return {"status": "success", "message": f"Proveedor OIDC {provider_id} actualizado correctamente."}
    except Exception as e:
        conn.rollback()
        print(f"ERROR DB UPDATE OIDC: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error al actualizar proveedor: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@router.delete("/{provider_id}")
@router.delete("/providers/{provider_id}")
def delete_oidc_provider(provider_id: int, admin_payload: dict = Depends(verify_admin_token)):
    """Elimina un proveedor OIDC."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM oidc_providers WHERE id = %s RETURNING id", (provider_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Proveedor OIDC no encontrado.")
        conn.commit()
        return {"status": "success", "message": f"Proveedor OIDC {provider_id} eliminado correctamente."}
    finally:
        cursor.close()
        conn.close()
