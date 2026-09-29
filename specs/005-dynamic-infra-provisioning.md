# Spec 005: Ciclo de Vida de Nodos de Infraestructura

## 1. Resumen
Esta especificación define la gestión del **registro** de nodos de infraestructura desde el panel web, su ciclo de vida dentro del clúster, el procedimiento de destrucción total de la infraestructura y la configuración de HTTPS.

> **Alta de nodos desde el panel web: retirada.** El proyecto ya **no** permite crear nodos de infraestructura desde el frontend ni desde la API. Los nodos se incorporan a la infraestructura exclusivamente por el despliegue inicial con `deploy-infra.yml`. Se conservan la consulta, la edición, la actualización de servicios y la eliminación de nodos ya existentes.

## 2. Alcance Actual del Panel Web

### 2.1 Endpoints vigentes

Todos bajo el prefijo `/api/v1/admin`, protegidos con el perfil `infra_manager`:

| Método | Ruta | Función | Estado |
|--------|------|---------|--------|
| GET | `/infra` | Listar nodos registrados | Vigente |
| GET | `/infra/component-types` | Catálogo de tipos de componente | Vigente |
| PUT | `/infra/{node_id}` | Editar los datos de un nodo | Vigente |
| DELETE | `/infra/{node_id}` | Eliminar el registro de un nodo | Vigente |
| POST | `/infra/{node_id}/update` | Actualizar el servicio del nodo | Vigente |

Endpoints retirados por estar exclusivos del alta de nodos nuevos: `POST /infra`, `GET /infra/public-key` y `POST /api/infrastructure/`.

### 2.2 Consulta de Nodos (`GET /infra`)
Devuelve el listado de `infrastructure_nodes` con `id`, `hostname`, `ip_address`, `service_ip`, `component_type`, `port`, `status`, `description` y `updated_at`. El frontend lo renderiza en tarjetas con las acciones **Editar**, **Update** y **Eliminar**.

### 2.3 Edición de Nodos (`PUT /infra/{node_id}`)
Actualiza `hostname`, `ip_address`, `service_ip`, `component_type`, `port`, `status` y `description` del nodo existente. Si `service_ip` no se informa, se assume el valor de `ip_address`. No ejecuta Ansible ni toca la máquina remota: es una edición de metadatos del registro.

### 2.4 Actualización de Servicios (`POST /infra/{node_id}/update`)
Ejecuta el playbook `install-binaries.yml` de forma síncrona contra el nodo:

1. Obtiene `hostname`, `ip_address`, `service_ip` y `component_type` del registro.
2. Resuelve la IP objetivo: `service_ip` o, en su defecto, `ip_address`.
3. Detecta si el destino es local (`127.0.0.1`, `::1` o la IP del host) y, en ese caso, añade `ansible_connection=local`.
4. Invoca el playbook con inventario inline apuntando al nodo destino, pasando `servicio=<component_type>`, `gestionar_servicios=true` y la IP de Pyroscope.
5. Devuelve `200 OK` con `stdout` si `returncode == 0`; en caso contrario devuelve `500` con la salida de error, o `504` si se excede el tiempo límite.

Al ser una operación sobre un nodo ya provisionado, no requiere usuario bootstrap, clave SSH ni onboarding previo.

### 2.5 Eliminación de Nodos (`DELETE /infra/{node_id}`)
Elimina el registro de `infrastructure_nodes`. No desinstala el software del sistema operativo remoto: la eliminación de binarios y servicios se realiza con `destroy-infra.yml`.

### 2.6 Interfaz Web
- El modal de infraestructura es exclusivamente de **edición**; el botón «Agregar Nodo», el campo «Usuario Bootstrap» y el bloque de llave pública se retiraron.
- El guardado emite siempre `PUT /api/v1/admin/infra/{id}`.
- Se conservan el botón «Actualizar» (refresca el listado), y las acciones por tarjeta: **Editar**, **Update** y **Eliminar**.

## 3. Incorporación de Nodos por Despliegue Inicial
Los nodos se incorporan ejecutando el playbook de despliegue, no desde el panel. `deploy-infra.yml` define las variables de credenciales y de rutas de almacenamiento (`nombre_usuario`, `nombre_username`, `*_storage_path`) que consumen los roles del clúster. Cualquier nodo nuevo debe añadirse a `inventory.ini` antes de ejecutar `deploy-infra.yml`.

## 4. Flujo de Ejecución del Destroy

### 4.1 Propósito
El playbook `destroy-infra.yml` debe eliminar completamente la infraestructura del sistema, incluyendo servicios, contenedores, volúmenes, imágenes, binarios y el usuario `anomalia`, sin necesidad de ejecutar comandos adicionales manualmente.

### 4.2 Tareas de Limpieza

| Elemento | Acción |
|----------|--------|
| Servicios systemd | Detener, deshabilitar y eliminar archivos de servicio |
| Contenedores Docker | `docker compose down -v` en backend, forzar eliminación de contenedores específicos |
| Volúmenes Docker | `docker volume prune -f` |
| Redes Docker | `docker network prune -f` |
| Imágenes Docker | `docker image prune -a -f` |
| Binarios en `/usr/local/bin` | Eliminar todos los binarios del ecosistema (vmstorage, vminsert, vmselect, vlstorage, vlinsert, vlselect, vtstorage, vtinsert, vtselect, vmauth, vmagent, vmalert, alertmanager, pyroscope, anomalia_parser) |
| Usuario `anomalia` | Eliminar del sistema con `remove: yes` |
| Directorios de datos | Eliminar `/var/lib/anomalia`, `/etc/anomalia`, `/opt/anomalia` |

### 4.3 Posterior al Destroy
Una vez ejecutado `destroy-infra.yml`, el sistema está limpio para ejecutar `deploy-infra.yml` desde cero, sin necesidad de intervención manual adicional.

## 5. Configuración HTTPS

### 5.1 Propósito
La aplicación soporta HTTPS con certificados de confianza del usuario. Si no se proporcionan certificados, la aplicación se levanta por defecto en HTTP.

### 5.2 Flujo de Decisión

```
¿Existen certificados en /opt/anomalia/certs/?
  ├─ Sí → Levantar con HTTPS (puerto 443)
  └─ No → Levantar con HTTP (puerto 8000)
```

### 5.3 Configuración de Certificados

1. Colocar los certificados en `/opt/anomalia/certs/`:
   - `fullchain.pem` - certificado completo
   - `privkey.pem` - clave privada

2. Reiniciar el contenedor:
   ```bash
   docker restart anomalia_gw
   ```

### 5.4 Consideraciones de Seguridad

- Los certificados deben ser de confianza del usuario (CA certificada)
