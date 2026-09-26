from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from typing import List, Optional
import psycopg2
import subprocess
import socket
from ..database import get_db_connection
from ..models import (
    UserCreateRequest, 
    UserUpdateRequest, 
    RoleCreateUpdatePayload, 
    ProfileCreateUpdatePayload, 
    TenantPayload,
    AuthNodePayload
)
from ..auth import verify_admin_token, hash_password, get_current_user_profiles, verify_profile_access

router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])

@router.get("/catalogs", dependencies=[Depends(verify_any_user_token := verify_profile_access("users_manager"))])
def get_catalogs():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, description FROM roles ORDER BY id ASC;")
        roles = [{"name": r[0], "description": r[1]} for r in cursor.fetchall()]

        cursor.execute("SELECT id, name, type, environment, port, description FROM tenants ORDER BY id ASC;")
        tenants = [{
            "id": t[0], "name": t[1], "type": t[2], 
            "environment": t[3], "port": t[4], "description": t[5]
        } for t in cursor.fetchall()]

        cursor.execute("SELECT id, code, name, description FROM profiles ORDER BY id ASC;")
        profiles = [{
            "id": p[0], "code": p[1], "name": p[2], "description": p[3]
        } for p in cursor.fetchall()]

        return {"roles": roles, "tenants": tenants, "profiles": profiles}
    finally:
        cursor.close()
        conn.close()

# --- USERS (users_manager) ---
@router.get("/users", dependencies=[Depends(verify_profile_access("users_manager"))])
def get_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, is_active FROM users ORDER BY id ASC;")
        user_rows = cursor.fetchall()
        users = []
        for ur in user_rows:
            uid, uname, is_act = ur[0], ur[1], ur[2]
            
            cursor.execute("SELECT r.name FROM user_roles sub JOIN roles r ON sub.role_id = r.id WHERE sub.user_id = %s;", (uid,))
            uroles = [row[0] for row in cursor.fetchall()]

            cursor.execute("SELECT t.name FROM user_tenants sub JOIN tenants t ON sub.tenant_id = t.id WHERE sub.user_id = %s;", (uid,))
            utenants = [row[0] for row in cursor.fetchall()]

            users.append({
                "id": uid,
                "username": uname,
                "is_active": bool(is_act),
                "roles": uroles,
                "tenants": utenants
            })
        return {"users": users}
    finally:
        cursor.close()
        conn.close()

@router.post("/users", dependencies=[Depends(verify_profile_access("users_manager"))])
def create_user(payload: UserCreateRequest):
    if payload.password_confirm and payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail="Las contraseñas no coinciden.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        hashed_pw = hash_password(payload.password)
        cursor.execute(
            "INSERT INTO users (username, password_hash, is_active) VALUES (%s, %s, %s) RETURNING id;",
            (payload.username, hashed_pw, True if payload.is_active else False)
        )
        user_id = cursor.fetchone()[0]

        if payload.roles:
            for r_name in payload.roles:
                cursor.execute("SELECT id FROM roles WHERE name = %s;", (r_name,))
                role_row = cursor.fetchone()
                if role_row:
                    cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s);", (user_id, role_row[0]))

        if payload.tenants:
            for t_name in payload.tenants:
                cursor.execute("SELECT id FROM tenants WHERE name = %s;", (t_name,))
                tenant_row = cursor.fetchone()
                if tenant_row:
                    cursor.execute("INSERT INTO user_tenants (user_id, tenant_id) VALUES (%s, %s);", (user_id, tenant_row[0]))

        conn.commit()
        return {"status": "success", "message": "Usuario creado correctamente", "id": user_id}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe.")
    finally:
        cursor.close()
        conn.close()

@router.put("/users/{user_id}", dependencies=[Depends(verify_profile_access("users_manager"))])
def update_user(user_id: int, payload: UserUpdateRequest):
    if payload.password and payload.password_confirm and payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail="Las contraseñas no coinciden.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE id = %s;", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        
        if payload.username is not None:
            cursor.execute("UPDATE users SET username = %s WHERE id = %s;", (payload.username, user_id))
        if payload.is_active is not None:
            cursor.execute("UPDATE users SET is_active = %s WHERE id = %s;", (True if payload.is_active else False, user_id))
        if payload.password:
            hashed_pw = hash_password(payload.password)
            cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s;", (hashed_pw, user_id))

        if payload.roles is not None:
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s;", (user_id,))
            for r_name in payload.roles:
                cursor.execute("SELECT id FROM roles WHERE name = %s;", (r_name,))
                role_row = cursor.fetchone()
                if role_row:
                    cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s);", (user_id, role_row[0]))

        if payload.tenants is not None:
            cursor.execute("DELETE FROM user_tenants WHERE user_id = %s;", (user_id,))
            for t_name in payload.tenants:
                cursor.execute("SELECT id FROM tenants WHERE name = %s;", (t_name,))
                tenant_row = cursor.fetchone()
                if tenant_row:
                    cursor.execute("INSERT INTO user_tenants (user_id, tenant_id) VALUES (%s, %s);", (user_id, tenant_row[0]))

        conn.commit()
        return {"status": "success", "message": "Usuario actualizado correctamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.delete("/users/{user_id}", dependencies=[Depends(verify_profile_access("users_manager"))])
def delete_user(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM user_roles WHERE user_id = %s;", (user_id,))
        cursor.execute("DELETE FROM user_tenants WHERE user_id = %s;", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s;", (user_id,))
        conn.commit()
        return {"status": "success", "message": "Usuario eliminado correctamente"}
    finally:
        cursor.close()
        conn.close()

# --- TENANTS (tenants_manager) ---
@router.get("/tenants", dependencies=[Depends(verify_profile_access("tenants_manager"))])
def get_tenants_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, type, account_id, project_id, environment, port, description FROM tenants ORDER BY id ASC;")
        rows = cursor.fetchall()
        tenants = []
        for r in rows:
            tenants.append({
                "id": r[0], "name": r[1], "type": r[2], 
                "account_id": r[3], "project_id": r[4], 
                "environment": r[5], "port": r[6], "description": r[7]
            })
        return {"tenants": tenants}
    finally:
        cursor.close()
        conn.close()

@router.post("/tenants", dependencies=[Depends(verify_profile_access("tenants_manager"))])
def create_tenant(payload: TenantPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO tenants (name, type, account_id, project_id, environment, port, description) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;",
            (payload.name, payload.type, payload.account_id, payload.project_id, payload.environment, payload.port, payload.description)
        )
        tenant_id = cursor.fetchone()[0]
        conn.commit()
        return {"status": "success", "message": "Tenant creado correctamente", "id": tenant_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.put("/tenants/{tenant_id}", dependencies=[Depends(verify_profile_access("tenants_manager"))])
def update_tenant(tenant_id: int, payload: TenantPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE tenants SET name = %s, type = %s, account_id = %s, project_id = %s, environment = %s, port = %s, description = %s WHERE id = %s;",
            (payload.name, payload.type, payload.account_id, payload.project_id, payload.environment, payload.port, payload.description, tenant_id)
        )
        conn.commit()
        return {"status": "success", "message": "Tenant actualizado correctamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.delete("/tenants/{tenant_id}", dependencies=[Depends(verify_profile_access("tenants_manager"))])
def delete_tenant(tenant_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM user_tenants WHERE tenant_id = %s;", (tenant_id,))
        cursor.execute("DELETE FROM role_tenants WHERE tenant_id = %s;", (tenant_id,))
        cursor.execute("DELETE FROM tenants WHERE id = %s;", (tenant_id,))
        conn.commit()
        return {"status": "success", "message": "Tenant eliminado correctamente"}
    finally:
        cursor.close()
        conn.close()

# --- ROLES (roles_manager) ---
@router.get("/roles", dependencies=[Depends(verify_profile_access("roles_manager"))])
def get_roles_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, description FROM roles ORDER BY id ASC;")
        rows = cursor.fetchall()
        roles = []
        for r in rows:
            cursor.execute("""
                SELECT t.name FROM role_tenants rt JOIN tenants t ON rt.tenant_id = t.id WHERE rt.role_id = %s;
            """, (r[0],))
            r_tenants = [t[0] for t in cursor.fetchall()]

            cursor.execute("""
                SELECT p.code FROM role_profiles rp JOIN profiles p ON rp.profile_id = p.id WHERE rp.role_id = %s;
            """, (r[0],))
            r_profiles = [p[0] for p in cursor.fetchall()]

            roles.append({
                "id": r[0], "name": r[1], "description": r[2],
                "tenants": r_tenants, "profiles": r_profiles
            })
        return {"roles": roles}
    finally:
        cursor.close()
        conn.close()

@router.post("/roles", dependencies=[Depends(verify_profile_access("roles_manager"))])
def create_role(payload: RoleCreateUpdatePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO roles (name, description) VALUES (%s, %s) RETURNING id;", (payload.name, payload.description))
        role_id = cursor.fetchone()[0]

        if payload.tenants:
            for t_name in payload.tenants:
                cursor.execute("SELECT id FROM tenants WHERE name = %s;", (t_name,))
                t_row = cursor.fetchone()
                if t_row:
                    cursor.execute("INSERT INTO role_tenants (role_id, tenant_id) VALUES (%s, %s);", (role_id, t_row[0]))

        if payload.profiles:
            for p_code in payload.profiles:
                cursor.execute("SELECT id FROM profiles WHERE code = %s;", (p_code,))
                p_row = cursor.fetchone()
                if p_row:
                    cursor.execute("INSERT INTO role_profiles (role_id, profile_id) VALUES (%s, %s);", (role_id, p_row[0]))

        conn.commit()
        return {"status": "success", "message": "Rol creado correctamente", "id": role_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.put("/roles/{role_id}", dependencies=[Depends(verify_profile_access("roles_manager"))])
def update_role(role_id: int, payload: RoleCreateUpdatePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE roles SET name = %s, description = %s WHERE id = %s;", (payload.name, payload.description, role_id))
        
        cursor.execute("DELETE FROM role_tenants WHERE role_id = %s;", (role_id,))
        if payload.tenants:
            for t_name in payload.tenants:
                cursor.execute("SELECT id FROM tenants WHERE name = %s;", (t_name,))
                t_row = cursor.fetchone()
                if t_row:
                    cursor.execute("INSERT INTO role_tenants (role_id, tenant_id) VALUES (%s, %s);", (role_id, t_row[0]))

        cursor.execute("DELETE FROM role_profiles WHERE role_id = %s;", (role_id,))
        if payload.profiles:
            for p_code in payload.profiles:
                cursor.execute("SELECT id FROM profiles WHERE code = %s;", (p_code,))
                p_row = cursor.fetchone()
                if p_row:
                    cursor.execute("INSERT INTO role_profiles (role_id, profile_id) VALUES (%s, %s);", (role_id, p_row[0]))

        conn.commit()
        return {"status": "success", "message": "Rol actualizado correctamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.delete("/roles/{role_id}", dependencies=[Depends(verify_profile_access("roles_manager"))])
def delete_role(role_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM user_roles WHERE role_id = %s;", (role_id,))
        cursor.execute("DELETE FROM role_tenants WHERE role_id = %s;", (role_id,))
        cursor.execute("DELETE FROM role_profiles WHERE role_id = %s;", (role_id,))
        cursor.execute("DELETE FROM roles WHERE id = %s;", (role_id,))
        conn.commit()
        return {"status": "success", "message": "Rol eliminado correctamente"}
    finally:
        cursor.close()
        conn.close()

# --- PROFILES (profile_manager) ---
@router.get("/profiles", dependencies=[Depends(verify_profile_access("profile_manager"))])
def get_profiles_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, code, name, description FROM profiles ORDER BY id ASC;")
        rows = cursor.fetchall()
        profiles = [{"id": p[0], "code": p[1], "name": p[2], "description": p[3]} for p in rows]
        return {"profiles": profiles}
    finally:
        cursor.close()
        conn.close()

@router.post("/profiles", dependencies=[Depends(verify_profile_access("profile_manager"))])
def create_profile(payload: ProfileCreateUpdatePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        code = payload.code if payload.code else payload.name.lower().replace(" ", "_")
        cursor.execute("INSERT INTO profiles (code, name, description) VALUES (%s, %s, %s) RETURNING id;", (code, payload.name, payload.description))
        profile_id = cursor.fetchone()[0]
        conn.commit()
        return {"status": "success", "message": "Perfil creado correctamente", "id": profile_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.put("/profiles/{profile_id}", dependencies=[Depends(verify_profile_access("profile_manager"))])
def update_profile(profile_id: int, payload: ProfileCreateUpdatePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        code = payload.code if payload.code else payload.name.lower().replace(" ", "_")
        cursor.execute("UPDATE profiles SET code = %s, name = %s, description = %s WHERE id = %s;", (code, payload.name, payload.description, profile_id))
        conn.commit()
        return {"status": "success", "message": "Perfil actualizado correctamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.delete("/profiles/{profile_id}", dependencies=[Depends(verify_profile_access("profile_manager"))])
def delete_profile(profile_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM role_profiles WHERE profile_id = %s;", (profile_id,))
        cursor.execute("DELETE FROM profiles WHERE id = %s;", (profile_id,))
        conn.commit()
        return {"status": "success", "message": "Perfil eliminado correctamente"}
    finally:
        cursor.close()
        conn.close()

# --- INFRASTRUCTURE (infra_manager) ---
@router.get("/infra", dependencies=[Depends(verify_profile_access("infra_manager"))])
def get_infra_nodes():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, hostname, ip_address, service_ip, component_type, port, status, description, updated_at FROM infrastructure_nodes ORDER BY id ASC;")
        rows = cursor.fetchall()
        nodes = []
        for r in rows:
            nodes.append({
                "id": r[0],
                "hostname": r[1],
                "ip_address": r[2],       
                "service_ip": r[3] if r[3] else r[2],  
                "component_type": r[4],
                "port": r[5],
                "status": r[6],
                "description": r[7],
                "updated_at": str(r[8]) if r[8] else None
            })
        return {"nodes": nodes}
    finally:
        cursor.close()
        conn.close()

@router.post("/infra", dependencies=[Depends(verify_profile_access("infra_manager"))])
def create_infra_node(payload: AuthNodePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        svc_ip = payload.service_ip if payload.service_ip else payload.ip_address
        cursor.execute(
            "INSERT INTO infrastructure_nodes (hostname, ip_address, service_ip, component_type, port, status, description) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;",
            (payload.hostname, payload.ip_address, svc_ip, payload.component_type, payload.port, payload.status, payload.description)
        )
        node_id = cursor.fetchone()[0]
        conn.commit()
        return {"status": "success", "message": "Nodo creado correctamente", "id": node_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.put("/infra/{node_id}", dependencies=[Depends(verify_profile_access("infra_manager"))])
def update_infra_node(node_id: int, payload: AuthNodePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM infrastructure_nodes WHERE id = %s;", (node_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Nodo no encontrado.")
        
        svc_ip = payload.service_ip if payload.service_ip else payload.ip_address
        cursor.execute(
            "UPDATE infrastructure_nodes SET hostname = %s, ip_address = %s, service_ip = %s, component_type = %s, port = %s, status = %s, description = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
            (payload.hostname, payload.ip_address, svc_ip, payload.component_type, payload.port, payload.status, payload.description, node_id)
        )
        conn.commit()
        return {"status": "success", "message": "Nodo actualizado correctamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.delete("/infra/{node_id}", dependencies=[Depends(verify_profile_access("infra_manager"))])
def delete_infra_node(node_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM infrastructure_nodes WHERE id = %s;", (node_id,))
        conn.commit()
        return {"status": "success", "message": "Nodo eliminado correctamente"}
    finally:
        cursor.close()
        conn.close()

@router.post("/infra/{node_id}/update", dependencies=[Depends(verify_profile_access("infra_manager"))])
def run_infra_ansible_update(node_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, hostname, ip_address, service_ip, component_type, port, status, description, admin_username, admin_password FROM infrastructure_nodes WHERE id = %s;", 
            (node_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Nodo no encontrado en la base de datos.")
        
        node = {
            "id": row[0],
            "hostname": row[1],
            "ip_address": row[2],
            "service_ip": row[3] if row[3] else row[2],
            "component_type": row[4],
            "port": row[5],
            "status": row[6],
            "description": row[7],
            "admin_username": row[8] if row[8] else "anomalia",
            "admin_password": row[9] if row[9] else ""
        }
    finally:
        cursor.close()
        conn.close()

    playbook_path = "/app/playbooks/install-binaries.yml"
    target_ip = node["ip_address"]
    admin_user = node["admin_username"]
    admin_pass = node["admin_password"]
    component = node["component_type"]

    cmd = [
        "ansible-playbook",
        "-i", f"{target_ip},",
        playbook_path,
        "-e", f"ansible_user={admin_user}",
        "-e", f"servicio={component} gestionar_servicios=true"
    ]

    if admin_pass:
        cmd.extend([
            "-e", f'ansible_password="{admin_pass}"',
            "-e", f'ansible_become_password="{admin_pass}"'
        ])

    try:
        result = subprocess.run(
            cmd,
            cwd="/app/playbooks",
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            return {"status": "success", "message": "Playbook ejecutado exitosamente OK.", "stdout": result.stdout}
        else:
            error_details = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            raise HTTPException(status_code=500, detail=error_details)
            
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="El playbook excedió el tiempo límite de ejecución (Timeout).")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
