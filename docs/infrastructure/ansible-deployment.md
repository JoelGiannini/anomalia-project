# Despliegue de Infraestructura (Ansible)

El aprovisionamiento, actualización y destrucción de la infraestructura de observabilidad de Anomalia se gestiona íntegramente mediante playbooks y roles de **Ansible** (`ansible-infra/`).

---

## 🛠️ Prerrequisitos de Plataforma

### Nodo de Control (Ansible Controller)
- **ansible-core** >= 2.10 (probado con `ansible 2.10.8`).
- **Sin dependencias externas:** El rol `victoria_firewall` utiliza exclusivamente módulos nativos de `ansible.builtin` (`firewall-cmd` para RHEL o reglas `iptables` para Debian/Ubuntu). No requiere colecciones adicionales.
- `openssl` para la generación de secretos compartidos.

### Nodos Destino (Managed Nodes)
- **Sistemas Operativos Soportados:** Debian 11/12, Ubuntu 20.04 / 22.04 / 24.04 LTS, RHEL 8/9 y derivados (Rocky / Alma / CentOS Stream).
- **Arquitectura:** `x86_64` (amd64) o `arm64` (aarch64).
- **Init System:** `systemd` obligatorio.
- **Contenedores:** Docker CE (socket activo, grupo `docker`) o Podman rootful, con soporte para `docker compose` (v2), `docker-compose` (v1) o `podman-compose`.

---

## 🚀 Comandos Clave de Operación

### 1. Verificación de Sintaxis
```bash
cd ansible-infra
ansible-playbook -i inventory.ini deploy-infra.yml --syntax-check
```

### 2. Despliegue Completo de la Plataforma
```bash
cd ansible-infra
ansible-playbook -i inventory.ini deploy-infra.yml
```

### 3. Destrucción Limpia del Stack (`destroy-infra.yml`)
```bash
cd ansible-infra
ansible-playbook -i inventory.ini destroy-infra.yml
```
{% hint style="info" %}
El playbook de destrucción detecta automáticamente el motor de contenedores y elimina contenedores, redes (`anomalia_aiops-net`), volúmenes y unidades systemd de Victoria y del firewall, manteniendo intactas las imágenes base cacheadas (`postgres`, `ollama`) y los certificados TLS en `/opt/anomalia/certs`. Además, retira las unidades **derivadas** `anomalia-vmalert-*.service` (vmalert por-tenant) descubiertas por `find`, sin hardcodear slugs.
%}{% endhint %}

### 4. Topología Flexible (inventario = única fuente)
La topología se decide **libremente en `inventory.ini`**: quien instala coloca las IPs en cada grupo (`vlogs_*_nodes`, `vm_*_nodes`, `vt_*_nodes`, `pyroscope_nodes`, `vmauth_nodes`, `vmagent_nodes`, `alertmanager_nodes`, `vmalert_nodes`, `backend_nodes`, `parses_nodes`) y un **mismo host puede pertenecer a cualquier combinación de grupos**. Cada unit systemd se despliega únicamente en los hosts de su grupo (no se asume un layout monolítico). Las referencias cruzadas entre componentes usan `hostvars[groups['X'][0]]` prefiriendo la IP de servicio (`*_ip`) con fallback a `ansible_host` y `127.0.0.1`. Detalle completo en `specs/013-deployment-topology-and-idempotency.md`.

---

## 🔄 Mecanismos Avanzados de Sincronización

- **Regeneración Incremental de Scrapes (`sync-scrapes.yml`):** Al desplegar o dar de baja una instancia vmalert por tenant, se encola automáticamente un proceso que regenera la configuración completa de `vmagent` y `vmauth` en los nodos correspondientes sin necesidad de reinstalar los binarios base.
- **Sincronización de Reglas (`sync-vmalert-rules.yml`):** Permite materializar las reglas YAML almacenadas en la base de datos hacia las rutas dedicadas en cada nodo (`/etc/anomalia/vmalert/<tenant_slug>/alert_rules.yml`) aplicando recarga en caliente (`/-/reload`).

### 5. Orden de Roles y Provisioning de Parses
- El rol `parses` corre **antes** que el rol `backend` y espera readiness del puerto (`wait_for`): el gateway reprovisiona el proyecto de Parses al arrancar, por lo que Perses debe estar listo primero.
- Tras un destroy+deploy los datos de Parses se pierden (`/perses` sin volumen) y el backend ejecuta un **catch-up no bloqueante al arranque** que recrea project + datasources + dashboards para todos los usuarios activos (idempotente, con reintentos). Detalle en `specs/008-parses-datasources-and-tenant-scoping.md`.
