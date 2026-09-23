from fastapi import APIRouter, Depends, HTTPException
from typing import List
import subprocess
import socket
from ..database import get_db_connection
from ..models import AuthNodePayload
from ..auth import verify_admin_token, get_current_user_profiles

router = APIRouter(prefix="/api/infrastructure", tags=["Infrastructure"], dependencies=[Depends(verify_admin_token)])

def verify_infra_manager(profiles: List[str] = Depends(get_current_user_profiles)):
    """Verifica que el usuario posea el perfil de gestión de infraestructura."""
    if "Infra Management Profile" not in profiles and "admin" not in profiles:
        raise HTTPException(
            status_code=403, 
            detail="Acceso denegado: Se requiere el perfil 'Infra Management Profile'."
        )
    return True

@router.get("/", dependencies=[Depends(verify_infra_manager)])
def get_infra_nodes():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, hostname, ip_address, service_ip, component_type, port, status, description FROM infrastructure_nodes ORDER BY id ASC;")
        rows = cursor.fetchall()
        nodes = []
        for r in rows:
            nodes.append({
                "id": r[0],
                "hostname": r[1],
                "ip_address": r[2],  # IP de Host
                "service_ip": r[3] if r[3] else r[2],  # IP de Servicio
                "component_type": r[4],
                "port": r[5],
                "status": r[6],
                "description": r[7],
                "actions": {
                    "can_update": True,
                    "update_endpoint": f"/api/infrastructure/{r[0]}/update"
                }
            })
        return {"nodes": nodes}
    finally:
        cursor.close()
        conn.close()

@router.post("/", dependencies=[Depends(verify_infra_manager)])
def create_infra_node(payload: AuthNodePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        svc_ip = payload.service_ip if payload.service_ip else payload.ip_address
        cursor.execute(
            """INSERT INTO infrastructure_nodes (hostname, ip_address, service_ip, component_type, port, status, description) 
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;""",
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

@router.put("/{node_id}", dependencies=[Depends(verify_infra_manager)])
def update_infra_node(node_id: int, payload: AuthNodePayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM infrastructure_nodes WHERE id = %s;", (node_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Nodo no encontrado.")

        svc_ip = payload.service_ip if payload.service_ip else payload.ip_address
        cursor.execute(
            """UPDATE infrastructure_nodes 
               SET hostname = %s, ip_address = %s, service_ip = %s, component_type = %s, port = %s, status = %s, description = %s, updated_at = CURRENT_TIMESTAMP 
               WHERE id = %s""",
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

@router.delete("/{node_id}", dependencies=[Depends(verify_infra_manager)])
def delete_infra_node(node_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM infrastructure_nodes WHERE id = %s;", (node_id,))
        conn.commit()
        return {"status": "success", "message": "Nodo eliminado correctamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@router.post("/{node_id}/update", dependencies=[Depends(verify_infra_manager)])
def run_infra_update_playbook(node_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT hostname, ip_address, service_ip, component_type FROM infrastructure_nodes WHERE id = %s;", (node_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Nodo de infraestructura no encontrado en la base de datos.")
        
        hostname, ip_address, service_ip, component_type = row
        target_ip = service_ip if service_ip else ip_address
        
        local_ips = {"127.0.0.1", "localhost", "::1"}
        try:
            local_ips.add(socket.gethostbyname(socket.gethostname()))
        except Exception:
            pass
        
        is_local = target_ip in local_ips or target_ip.startswith("127.")
        playbook_path = "/opt/anomalia/backend/playbooks/install-binaries.yml"
        
        cmd = [
            "sudo", "ansible-playbook",
            "-i", "127.0.0.1,",
            playbook_path,
            "-e", f"servicio={component_type} gestionar_servicios=true",
            "-e", f'pyroscope_ip="{target_ip},"'
        ]
        
        if is_local:
            cmd.extend(["-e", "ansible_connection=local"])
            
        result = subprocess.run(
            cmd,
            cwd="/opt/anomalia/backend/playbooks",
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            return {"status": "success", "message": f"Playbook ejecutado correctamente para {component_type} en {target_ip}", "stdout": result.stdout}
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Error desconocido en Ansible"
            raise HTTPException(status_code=500, detail=error_msg)
            
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="La ejecución del playbook de Ansible excedió el tiempo límite.")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
