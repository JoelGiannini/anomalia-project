import os
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClient
from passlib.context import CryptContext
from .database import get_db_connection

security = HTTPBearer()

# Configuración de hashing para contraseñas locales (Admin)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configuración de JWT para sesiones de administración locales
SECRET_KEY = os.getenv("ADMIN_JWT_SECRET", "super-secret-admin-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_admin_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_oidc_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Valida tokens emitidos por el Proveedor de Identidad OIDC externo (Operadores)"""
    token = credentials.credentials
    issuer_url = os.getenv("OIDC_ISSUER_URL", "http://keycloak:8080/realms/aiops")
    jwks_url = f"{issuer_url}/protocol/openid-connect/certs"
    
    try:
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer_url,
            options={"verify_aud": False}
        )
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Token OIDC inválido o expirado: {str(e)}"
        )

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Valida tokens JWT internos emitidos para el Administrador del Sistema"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        roles = payload.get("roles", [])
        primary_role = payload.get("role", "")
        
        if primary_role != "admin" and "admin" not in roles:
            raise HTTPException(status_code=403, detail="Privilegios de administrador requeridos.")
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Token de administración inválido o expirado."
        )

def verify_any_user_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Valida cualquier token JWT interno emitido, sin exigir un rol específico."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Token de autenticación inválido o expirado."
        )

def get_current_user_profiles(payload: dict = Depends(verify_any_user_token)):
    """Extrae y retorna los datos y roles del usuario del payload del token."""
    try:
        return {
            "username": payload.get("sub") or payload.get("username"),
            "role": payload.get("role"),
            "roles": payload.get("roles", [])
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudieron extraer los perfiles del usuario: {str(e)}"
        )

def verify_profile_access(required_profile: str):
    """Verifica si el usuario actual posee el perfil requerido a través de sus roles asignados."""
    def dependency(payload: dict = Depends(verify_any_user_token)):
        roles = payload.get("roles", [])
        primary_role = payload.get("role", "")
        
        all_user_roles = [primary_role] + roles if primary_role else roles
        if "admin" in all_user_roles:
            return payload  # El admin global tiene acceso a todo

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Consultar si alguno de los roles del usuario tiene asignado el perfil requerido
            format_strings = ','.join(['%s'] * len(all_user_roles)) if all_user_roles else "''"
            query = f"""
                SELECT COUNT(*) FROM role_profiles rp
                JOIN roles r ON rp.role_id = r.id
                JOIN profiles p ON rp.profile_id = p.id
                WHERE r.name IN ({format_strings}) AND p.code = %s;
            """
            cursor.execute(query, tuple(all_user_roles) + (required_profile,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                raise HTTPException(
                    status_code=403, 
                    detail=f"Acceso denegado. Se requiere el perfil '{required_profile}'."
                )
            return payload
        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error validando permisos: {str(e)}")
        finally:
            cursor.close()
            conn.close()
    return dependency
