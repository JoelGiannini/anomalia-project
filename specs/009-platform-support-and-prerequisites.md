# Spec 009 — Plataformas Soportadas, Prerequisitos y Despliegue Público

## 1. Objetivo

Definir el **perfil de plataforma** que soporta el stack Anomalia (distribuciones Linux,
arquitecturas, motores de contenedores y firewall), los **prerequisitos** que deben
cumplir los nodos de destino y el **nodo de control**, y las **recomendaciones de
despliegue público** (red, CIDRs y exposición de servicios).

## 2. Matriz de plataformas soportadas

| Eje | Soportado | No soportado |
|---|---|---|
| Distribuciones | Debian 11/12, Ubuntu 20.04/22.04/24.04 LTS, RHEL 8/9 y derivados (Rocky, Alma, CentOS Stream) | Alpine (no systemd), SUSE/SLES (no testeado), macOS/Windows/BSD |
| Arquitectura | `x86_64` (amd64, estándar), `arm64` (aarch64) | i386/armv7 (no se publican binarios) |
| Init system | systemd (PID 1) | sysvinit, OpenRC |
| Motores de contenedores | Docker CE (socket `/var/run/docker.sock`), Podman rootful (compat `podman-docker` o `podman-compose`) | Podman rootless con stack de puertos privilegiados (80/443) |
| Compose | `docker compose` (plugin v2), `docker-compose` (v1), `podman-compose` | `docker stack` / swarm |
| Firewall de host | `firewalld` (RHEL-familiar típico) → rich rules; ufw inactivo o ausencia de firewalld → cadena `iptables` (`nf_tables`) | N/A |

### 2.1 Arquitecturas

`install-binaries.yml` determina `anomalia_bin_arch = amd64 | arm64` a partir de
`ansible_architecture` y aborta con mensaje claro si no es soportada. Todos los filtros
de assets (VictoriaLogs, VictoriaMetrics cluster, VictoriaTraces, vmutils, Pyroscope,
Alertmanager) se construyen con ese fact.

## 3. Prerequisitos

=== 3.1 Nodo de control (donde corre Ansible)

- Solo Ansible `ansible-core` 2.10+ (`ansible` 2.10.8 probado). **No requiere
  colecciones ni pasos previos**: el rol `victoria_firewall` usa únicamente módulos
  `ansible.builtin` (`firewall-cmd` en RHEL, cadena iptables en Debian/Ubuntu), de modo
  que `deploy-infra.yml` y `destroy-infra.yml` se ejecutan en **un solo comando**.
- `openssl` (generación del secret compartido; task delegada a `localhost`).
- Conectividad de red a los targets y credenciales con `sudo` (o acceso root).

### 3.2 Cada nodo de destino

- Distribución Linux de la tabla §2, `x86_64` o `arm64`, con **systemd**.
- **Python 3** en `/usr/bin/python3` (fijado en `inventory.ini` vía
  `ansible_python_interpreter`).
- **Docker CE** con socket activo (grupo `docker`) **o** **Podman rootful**; al menos un
  comando Compose de los tres soportados (§2).
- **iptables** (`iptables-nft` en Ubuntu/Debian) si no se usará firewalld; **firewalld**
  activo en RHEL-family (rich rules nativas).
- Usuario `anomalia` creado por el despliegue, miembro de `sudo`/`wheel` + `docker`.

### 3.3 Aislamiento del firewall

`victoria_firewall` detecta automáticamente y usa:
1. **firewalld** si el servicio está activo (RHEL-family) → rich rules vía
   `firewall-cmd` (`--query-rich-rule` / `--add-rich-rule` / `--reload`, idempotente).
2. **iptables** en caso contrario (Debian/Ubuntu) → cadena `ANOMALIA_VICTORIA_READ`.

No se deshabilita el firewall de la distro en ningún caso: se respeta el mecanismo nativo.

## 4. Motores de contenedores y Compose

`deploy-infra.yml` (pre_tasks) detecta y expone facts por host:

| Fact | Valores |
|---|---|
| `anomalia_container_engine` | `docker` \| `podman` |
| `anomalia_compose_cmd` | `docker compose` \| `docker-compose` \| `podman-compose` |
| `anomalia_engine_cmd` | `docker` \| `podman` (para `pull`, `network create`) |
| `anomalia_engine_service` | `docker.service` \| `podman.socket` (dependencia del unit del firewall) |
| `anomalia_container_socket` | `/var/run/docker.sock` \| `/run/podman/podman.sock` (mount del gateway) |
| `anomalia_extra_host_gateway` | `host-gateway` (docker) \| `host.containers.internal` (podman) |

- Los roles `backend` y `parses` levantan los stacks con `{{ anomalia_compose_cmd }}`
  (v1 o v2 o podman-compose, indistinto).
- La red compartida `anomalia_aiops-net` se crea con `{{ anomalia_engine_cmd }}
  network create --driver bridge`.
- **Podman**: modo soportado = **rootful**, vía `podman-docker` (socket compat
  `/var/run/docker.sock` → `docker-compose`/`docker compose`) o `podman-compose`. El
  socket se expone al grupo `docker` para el usuario `anomalia`. Rootless NO soportado en
  el stack completo (bindea 80/443/5432/11434).

## 5. Dependencias Ansible

Los playbooks utilizan **solo módulos `ansible.builtin`**; no se requiere `ansible-galaxy`
ni colecciones adicionales. El despliegue y el destroy operan con `ansible-core` pelado:

```bash
cd ansible-infra
ansible-playbook -i inventory.ini deploy-infra.yml   # despliega todo
ansible-playbook -i inventory.ini destroy-infra.yml  # destruye todo
```

## 6. Despliegue público

Recomendaciones para disponibilizar el proyecto públicamente (sin mitigar el aislamiento):

1. **Nunca exponer los puertos de lectura** (`victoria_firewall_ports`: 8401, 8481, 8491,
   4040). Deben quedar solo accesibles desde el puente de contenedores, loopback y
   administración. Todo acceso público va por el **gateway TLS (443)** con autenticación
   (ver spec 007).
2. **CIDR del firewall**: el valor por defecto `172.16.0.0/12` cubre el pool por defecto
   de Docker pero es demasiado amplio para producción. Para exposición pública, acotar
   `victoria_firewall_allowed_sources` a la subred **exacta** del puente:
   ```bash
   docker network inspect anomalia_aiops-net \
     --format '{{.IPAM.Config.[0].Subnet}}'
   ```
   más los CIDRs de administración/VPN.
3. **Toggle** `victoria_firewall_enabled: false` cuando el entorno cloud (security group /
   network ACL) ya aísla esos puertos, dejando la barrera en la capa de red del proveedor.
4. En cloud, la barrera primaria es el **security group / network ACL**; el firewall del
   host (iptables/firewalld) es defensa en profundidad, no única.
5. Usar **certificados de una CA real** (Let's Encrypt) en `roles/certs` antes de exponer
   (spec 007 §7).

## 7. Teardown (`destroy-infra.yml`)

El destroy reutiliza los mismos facts de detección que el deploy
(`tasks/detect_container_stack.yml`, `tags: always`), por lo que es **agnóstico al motor y
a la versión de Compose** y no asume `docker compose` (v2). Si no detecta motor, avisa y
continúa con la limpieza del host.

Retira, en este orden:

1. **Aislamiento L4** de los puertos de lectura (`victoria_firewall_ports` y
   `victoria_firewall_allowed_sources` se toman de
   `roles/victoria_firewall/defaults/main.yml` vía `vars_files`, sin duplicar la lista):
   salto + cadena iptables `ANOMALIA_VICTORIA_READ` (con `-C`/`-D` en bucle, luego `-F` y
   `-X`), rich rules de firewalld (permanent + runtime) y `--reload`; después la unit
   `anomalia-victoria-firewall` (stop/disable + borrado). Se hace **antes** de borrar
   `/etc/anomalia`, que contiene el script de aplicación.
2. Unidades systemd de los backends Victoria, `/var/lib/anomalia`, `/etc/anomalia`,
   `/opt/anomalia/backend`, `/opt/anomalia/parses`, `/tmp/anomalia-binaries` y los binarios
   de `/usr/local/bin`; usuario `anomalia` (`remove: yes`).
3. **Contenedores**: `{{ anomalia_compose_cmd }} down -v --remove-orphans` por stack
   (si el directorio de despliegue existe), barrido de remanentes
   `{{ anomalia_engine_cmd }} ps -aq --filter name=anomalia_` y borrado de la red
   `anomalia_aiops-net`.

### 7.1 Alcance del borrado de imágenes y volúmenes

- **Acotado a Anomalia**: se listan y borran solo los recursos con label
  `com.docker.compose.project=backend|parses` (imágenes construidas por los stacks y
  volúmenes con nombre de Compose).
- `volume prune -f` (volúmenes anónimos huérfanos) sí se ejecuta.
- **Se conservan** las imágenes base compartidas (`postgres:15-alpine`,
  `ollama/ollama:latest`) y `/opt/anomalia/certs` (material TLS), para no afectar a otros
  proyectos del host ni forzar re-descargas en el siguiente deploy.
- No se ejecutan `image prune -a` ni `network prune` globales.

## 8. Fuera de alcance

- Podman rootless, SUSE/openSUSE, Alpine, macOS, Windows, arquitecturas no-x86_64/arm64.
- Aprovisionamiento multi-host sobre Docker swarm/overlay (la red `anomalia_aiops-net`
  es single-host).