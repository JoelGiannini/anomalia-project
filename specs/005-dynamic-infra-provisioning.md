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

Endpoints retirados por estar exclusivos del alta de nodos nuevos: `POST /infra`, `GET /infra/public-key` y `POST /api/infrastructure/`. También se retiró `POST /api/infrastructure/{node_id}/update`, duplicado muerto del update vigente (ver §2.7).

### 2.2 Consulta de Nodos (`GET /infra`)
Devuelve el listado de `infrastructure_nodes` con `id`, `hostname`, `ip_address`, `service_ip`, `component_type`, `port`, `status`, `description` y `updated_at`. El frontend lo renderiza en tarjetas con las acciones **Editar**, **Update** y **Eliminar**.

### 2.3 Edición de Nodos (`PUT /infra/{node_id}`)
Actualiza `hostname`, `ip_address`, `service_ip`, `component_type`, `port`, `status` y `description` del nodo existente. Si `service_ip` no se informa, se assume el valor de `ip_address`. No ejecuta Ansible ni toca la máquina remota: es una edición de metadatos del registro.

### 2.4 Actualización de Servicios (`POST /infra/{node_id}/update`)
Ejecuta el playbook `install-binaries.yml` de forma síncrona contra el nodo:

1. Obtiene `admin_username`, `admin_password`, `ip_address` y `component_type` del registro. La IP objetivo es `ip_address`.
2. Verifica precondiciones y responde `500` con mensaje explícito si falta `/app/playbooks/install-binaries.yml` en la imagen o si `ansible-playbook` no está instalado.
3. Verifica que `component_type` esté en `ANSIBLE_UPDATABLE_COMPONENTS`. Si no está, responde `400` con la lista de componentes soportados en lugar de ejecutar el playbook.
4. Escribe las variables extra en un archivo JSON `0600` dentro de un directorio privado temporal y lo pasa con `--extra-vars @archivo`. Las credenciales **no** van en `argv`, para que no queden legibles en `ps`. El directorio se borra en un `finally`.
5. Invoca `ansible-playbook -i <ip>, /app/playbooks/install-binaries.yml` con `ansible_user`, `servicio=<component_type>`, `gestionar_servicios=true`, `ansible_password` y `ansible_become_password`.
6. Devuelve `200 OK` con `stdout` si `returncode == 0`; en caso contrario devuelve `500` con STDOUT y STDERR del ansible, o `504` si se excede el tiempo límite de 300 s.

Todo fallo de `ansible-playbook` se escribe **también** en el log del contenedor (`logger.error` con nodo, componente, `returncode` y la salida completa), de modo que el diagnóstico no dependa de leer el body de la respuesta HTTP.

#### 2.4.2 Trampa: `{{ }}` dentro de un `when:`

Las seis secciones de `install-binaries.yml` filtraban el asset por regex con la
plantilla inline en el condicional:

```yaml
when: item.name is match(".*linux-amd64.*")   # INCORRECTO
```

Ansible marca el condicional como *unsafe* y falla en tiempo de ejecución con
`Conditional is marked as unsafe, and cannot be evaluated`. Como el playbook
devuelve `returncode != 0`, el endpoint respondía **`500`** para cualquier nodo.
La forma correcta es sacar la plantilla a `vars` y referenciarla desde `item`:

```yaml
vars:
  _pattern: "{{ servicio_pattern }}"
when: item.name is match(_pattern)
```

Los `{{ }}` de `vars:` se resuelven antes de evaluar el `when`, así el condicional
queda en formato seguro. Tareas afectadas: descarga, verificación de checksum,
extracción y servicio de cada una de las 6 familias de binarios.

Al ser una operación sobre un nodo ya provisionado, no requiere usuario bootstrap, clave SSH ni onboarding previo.

#### 2.4.1 Vocabulario de `component_type`

`infrastructure_nodes.component_type` es un identificador único que debe coincidir en tres lugares:

| Fuente | Valores |
|---|---|
| `roles/backend/templates/init.sql.j2` (seed) | 16 tipos: `vl*`, `vm*`, `vt*`, `vmagent`, `vmauth`, `vmalert`, `pyroscope`, `alertmanager`, `parses`, `backend` |
| `GET /infra/component-types` (catálogo del modal) | los mismos 16, cada uno con `updatable: bool` |
| `install-binaries.yml` (valores de `servicio`) | los 14 actualizables |

`parses` y `backend` se declaran con `updatable: false`: no existe sección en `install-binaries.yml` que los reinstale, se gestionan solo con `deploy-infra.yml`. `GET /infra` expone el mismo campo `updatable` por nodo y el frontend deshabilita el botón **Update** con un tooltip explicativo. Así se evita el falso «actualizado correctamente» que devolvía un playbook sin tareas aplicables.

### 2.5 Eliminación de Nodos (`DELETE /infra/{node_id}`)
Elimina el registro de `infrastructure_nodes`. No desinstala el software del sistema operativo remoto: la eliminación de binarios y servicios se realiza con `destroy-infra.yml`.

### 2.6 Interfaz Web
- El modal de infraestructura es exclusivamente de **edición**; el botón «Agregar Nodo», el campo «Usuario Bootstrap» y el bloque de llave pública se retiraron.
- El guardado emite siempre `PUT /api/v1/admin/infra/{id}`.
- Se conservan el botón «Actualizar» (refresca el listado), y las acciones por tarjeta: **Editar**, **Update** y **Eliminar**.
- El alert del **Update** muestra el `detail` real de la respuesta (STDOUT/STDERR del ansible), no un mensaje genérico. Antes el `detail` se descartaba y un fallo quedaba invisible salvo por un `500`.

### 2.7 Endpoint duplicado retirado
`POST /api/infrastructure/{node_id}/update` (router `infra_router.py`) se eliminó: nunca lo consumió el frontend, ejecutaba `-i 127.0.0.1,` hardcodeado ignorando la IP del nodo, pasaba la contraseña en `argv` y resolvía el host local de forma distinta al endpoint vigente. El router conserva `GET`, `PUT` y `DELETE` de `/api/infrastructure`.

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
| Binarios en `/usr/local/bin` | Eliminar todos los binarios del ecosistema (vmstorage, vminsert, vmselect, vlstorage, vlinsert, vlselect, vtstorage, vtinsert, vtselect, vmauth, vmagent, vmalert, alertmanager, pyroscope, anomalia_parses) |
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
