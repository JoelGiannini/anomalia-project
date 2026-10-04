# Despliegue de Infraestructura

El despliegue se gestiona íntegramente mediante **Ansible** (`ansible-infra/`).

## Prerequisitos

### Nodo de control (donde corre Ansible)
- Solo Ansible `ansible-core` >= 2.10 (`ansible 2.10.8` probado). **No requiere
  colecciones ni pasos previos**: el role `victoria_firewall` usa únicamente módulos
  `ansible.builtin` (`firewall-cmd` en RHEL, cadena iptables en Debian/Ubuntu).
- `openssl` (generación del secret compartido en el nodo de control).

### Cada nodo de destino
- Linux **Debian 11/12**, **Ubuntu 20.04/22.04/24.04 LTS**, o **RHEL 8/9** + derivados
  (Rocky/Alma/CentOS Stream), arquitectura **x86_64** o **arm64**, con **systemd**.
- **Python 3** (`/usr/bin/python3`), fijado vía `ansible_python_interpreter` en el inventario.
- **Docker CE** (socket activo, grupo `docker`) o **Podman rootful**. Al menos un comando
  Compose: `docker compose` (v2), `docker-compose` (v1) o `podman-compose`.
- **iptables** (Debian/Ubuntu) o **firewalld activo** (RHEL) — el role `victoria_firewall`
  detecta el backend automáticamente y usa el mecanismo nativo de la distro.

## Plataformas y motores soportados

Resumen (detalle completo en `specs/009-platform-support-and-prerequisites.md`):

| Eje | Soportado |
|---|---|
| Distros | Debian 11/12, Ubuntu 20.04/22.04/24.04 LTS, RHEL 8/9 + Rocky/Alma/CentOS Stream |
| Arquitectura | `x86_64` (amd64), `arm64` (aarch64) — `install-binaries.yml` aborta si no aplica |
| Init | systemd |
| Contenedores | Docker CE, Podman rootful (compat `podman-docker` o `podman-compose`) |
| Compose | v2 (`docker compose`), v1 (`docker-compose`), `podman-compose` |
| Firewall | firewalld (rich rules) o iptables (cadena `ANOMALIA_VICTORIA_READ`) — auto-detectado |

No soportado: Alpine (sin systemd), SUSE, macOS/Windows/BSD, Podman rootless con puertos
privilegiados, arquitecturas sin binarios publicados.

## Despliegue público

Antes de disponibilizar el proyecto públicamente (detalle en `specs/009`):

1. **No exponer los puertos de lectura** Victoria (8401, 8481, 8491, 4040): quedan solo en
   el puente de contenedores / loopback / administración. Todo acceso público va por el
   **gateway TLS (443)** con autenticación.
2. Acotar `victoria_firewall_allowed_sources` a la subred **exacta** del puente más los
   CIDRs de administración/VPN (en lugar del default `172.16.0.0/12`).
3. Poner `victoria_firewall_enabled: false` cuando el security group / network ACL del
   cloud ya aísla esos puertos (la barrera del proveedor pasa a ser la primaria).
4. Usar certificados de una CA real (Let's Encrypt) en `roles/certs`.

## Comandos Clave
- **Validación de sintaxis:**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini deploy-infra.yml --syntax-check
  ```
- **Despliegue completo:**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini deploy-infra.yml
  ```
- **Destrucción completa (destroy + teardown):**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini destroy-infra.yml
  ```
  El destroy detecta el motor y el comando Compose igual que el deploy, y retira:
  contenedores y red `anomalia_aiops-net`; imágenes y volúmenes de los proyectos compose
  `backend`/`parses`; las unidades systemd de Victoria y la del firewall; el aislamiento L4
  (cadena iptables `ANOMALIA_VICTORIA_READ` o rich rules de firewalld); datos, configuración
  (`/var/lib/anomalia`, `/etc/anomalia`, `/opt/anomalia/*`), binarios en `/usr/local/bin` y
  el usuario `anomalia`.
  **Se conservan a propósito:** las imágenes base `postgres`/`ollama` (quedan cacheadas) y
  `/opt/anomalia/certs` (material TLS). Detalle en `specs/009` §7.
- **Modelo de Ollama:** el role `backend` descarga `{{ ollama_model }}` (por defecto
  `llama3.2:1b`, var en `roles/backend/defaults/main.yml`) con `ollama pull` vía la API
  HTTP de Ollama (`127.0.0.1:11434`) justo después de levantar el stack, y verifica que
  quede en `/api/tags`. Es idempotente: si el volumen ya tiene el modelo, se salta el
  pull. Sin este paso el backend recibe `404` de Ollama (el contenedor arranca sin
  modelos). Detalle en `specs/003` §2.1.