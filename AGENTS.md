# Guía del Entorno para Agentes (AGENTS.md)

Este documento sirve como manual de referencia técnica para cualquier asistente o desarrollador que opere sobre el repositorio **Anomalia**. Define el stack tecnológico, los comandos de ejecución, validación y prueba, así como los protocolos de desarrollo.

---

## 1. Stack Tecnológico del Proyecto

### 1.1 Backend & API (`/backend`)
- **Lenguaje:** Python 3.10+
- **Framework Web:** FastAPI con servidor ASGI Uvicorn.
- **Base de Datos & ORM:** PostgreSQL 15, SQLAlchemy, Psycopg2.
- **Autenticación & Seguridad:** JWT (`python-jose`, `PyJWT`), Hashing (`passlib`, `bcrypt`), Integración OIDC.
- **Observabilidad & Telemetría:** OpenTelemetry (API, SDK, FastAPI Instrumentation, OTLP HTTP), Prometheus Client, Pyroscope.
- **Automatización:** Librería Ansible embebida.

### 1.2 Frontend Web (`/backend/frontend`)
- **Tecnologías:** HTML5, CSS3, JavaScript Vanilla (Modular: `api.js`, `state.js`, `ui.js`, `admin.js`, `main.js`).
- **Estilos:** Interfaz corporativa con temas personalizados.

### 1.3 Aplicación Móvil (`/mobile`)
- **Framework:** Flutter (SDK Dart `^3.13.2`).
- **Plataformas Soportadas:** Android (principal), iOS, Web, Linux, macOS, Windows.
- **Librerías Clave:** `http`, `shared_preferences`, `flutter_appauth` (OIDC), `url_launcher`, `app_links`.

### 1.4 Infraestructura y Automatización (`/ansible-infra`)
- **Herramienta de IaC:** Ansible (Playbooks y Roles).
- **Componentes Gestionados:**
  - Ecosistema Victoria (VictoriaMetrics, VictoriaLogs, VictoriaTraces, vmagent, vmalert, vmauth).
  - Alertas y Procesamiento: Alertmanager, Parses de Dashboards, Pyroscope.

---

## 2. Comandos de Entorno, Compilación y Testing

### 2.0 Secret Scanning (obligatorio antes de commitear)

El escaneo de secretos corre como hook de `pre-commit` en cada commit. Config
en `.gitleaks.toml` y `.pre-commit-config.yaml`. Detalle en
`specs/006-secret-scanning-gate.md`.

* **Escaneo manual del working tree:**
  ```bash
  gitleaks dir .
  ```
* **Escaneo manual del historial completo:**
  ```bash
  gitleaks git .
  ```
* **Ejecutar todos los hooks sobre el repo entero:**
  ```bash
  pre-commit run --all-files
  ```
* **Bypass de un hallazgo legítimo (preferir corregir el código):**
  ```bash
  SKIP=gitleaks git commit
  ```

* **Instalación** (Pop!_OS / Ubuntu, `~/.local/bin` ya en PATH):
  ```bash
  # gitleaks v8.30.1 linux_x64, siempre verificando el checksum oficial
  cd /tmp && curl -sSLO https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz
  curl -sSLO https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_checksums.txt
  sha256sum -c --ignore-missing gitleaks_8.30.1_checksums.txt
  tar xzf gitleaks_8.30.1_linux_x64.tar.gz && install -m 755 gitleaks ~/.local/bin/gitleaks

  pip3 install --user pre-commit
  pre-commit install
  ```

* **Variable de entorno requerida:** `opencode.json` referencia
  `CONTEXT7_API_KEY`. Si no está definida, el MCP de Context7 falla sin autenticar.
  ```bash
  export CONTEXT7_API_KEY="ctx7sk-..."
  ```

* **Limitación conocida:** gitleaks detecta secretos de alta entropía y de
  proveedor conocido. **No** detecta passwords débiles de diccionario. Los
  valores `anomal_password`, `admin_password` y `change-me-secret` de
  `ansible-infra/` quedan fuera de su alcance por diseño; están registrados
  como riesgo aceptado en la spec.

### 2.1 Prerequisitos de Plataforma (Ansible / Infra)

El stack soporta **Debian 11/12, Ubuntu 20.04/22.04/24.04 LTS y RHEL 8/9 +
derivados (Rocky/Alma/CentOS Stream)**, arquitectura `x86_64` o `arm64`, con
**systemd**. Contenedores: **Docker CE o Podman rootful**; Compose v1, v2 o
`podman-compose` (el depliegue lo detecta y abstrae por facts
`anomalia_*`). Firewall: **firewalld** (RHEL) o **iptables** (Debian/Ubuntu),
auto-detectado por el role `victoria_firewall` usando **solo módulos
ansible.builtin** (rich rules vía `firewall-cmd` o cadena iptables), por lo
que **no se requieren colecciones Ansible ni pasos previos**: el deploy y el
destroy se lanzan en un solo comando. Rootless Podman, Alpine, SUSE y
macOS/Windows **no soportados**.
* **Despliegue público:** no exponer los puertos de lectura de Victoria
  (8401/8481/8491/4040); todo acceso público por el gateway TLS (443). Acotar
  `victoria_firewall_allowed_sources` a la subred exacta del puente y CIDRs de
  administración/VPN; `victoria_firewall_enabled: false` si el security group
  del cloud ya aísla. Detalle en `specs/009-platform-support-and-prerequisites.md`.

### 2.2 Backend (FastAPI & Base de Datos)
* **Instalación de Dependencias:**
  ```bash
  cd backend
  pip install -r requirements.txt
  ```
* **Ejecución del Servidor de Desarrollo:**
  ```bash
  cd backend
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
* **Ejecución de Pruebas Unitarias (Pytest):**
  ```bash
  cd backend
  pytest
  ```
* **Validación de un dashboard contra Perses (solo lectura):**
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -H 'Content-Type: application/json' -d @dashboard.json \
    http://127.0.0.1:8090/api/validate/dashboards
  ```
  `200` = schema correcto; `4xx` = detalle del error en el cuerpo. Los dashboards
  nativos llevan el marcador `xAnomaliaDatasource`, que hay que sustituir antes con
  `parses_provisioner._resolve_panel_datasources()` (ver `specs/008` § 9).

### 2.3 Infraestructura (Ansible)
* **Verificación de Sintaxis de Playbooks:**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini deploy-infra.yml --syntax-check
  ```
* **Despliegue de Infraestructura:**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini deploy-infra.yml
  ```

### 2.4 Aplicación Móvil (Flutter)
* **Obtención de Paquetes:**
  ```bash
  cd mobile
  flutter pub get
  ```
* **Análisis Estático de Código:**
  ```bash
  cd mobile
  flutter analyze
  ```
* **Ejecución de Pruebas Flutter:**
  ```bash
  cd mobile
  flutter test
  ```

---

## 3. Guía de Operación para el Asistente (SSD Workflow)

### 3.1 Checklist SSD Obligatorio

**Antes de implementar cualquier cambio:**
- [ ] Consultar la spec relevante según el tipo de cambio:
  - Arquitectura general → `specs/001-architecture-overview.md`
  - Tenants/Alertmanager → `specs/002-tenant-alertmanager-provisioning.md`
  - Pipeline AIOps → `specs/003-aiops-alert-pipeline.md`
  - Seguridad/RBAC → `specs/004-rbac-and-security.md`
  - Ciclo de vida de nodos de infraestructura → `specs/005-dynamic-infra-provisioning.md`
  - Escaneo de secretos (gitleaks / pre-commit) → `specs/006-secret-scanning-gate.md`
  - Gateway HTTPS, certs y acceso por tenant → `specs/007-https-gateway-and-tenant-access.md`
  - Parses (dashboards, datasources y scoping por tenant) → `specs/008-parses-datasources-and-tenant-scoping.md`
  - Soporte de plataforma y prerrequisitos → `specs/009-platform-support-and-prerequisites.md`
  - Consolas de UI de telemetría (proxy de tickets, incluye Parses) → `specs/010-ui-console-proxy.md`
- [ ] Si no existe spec para lo que se va a hacer, crearla primero antes de implementar.

**Después de implementar:**
- [ ] Si el cambio afecta el comportamiento documentado → actualizar la spec existente.
- [ ] Si es una funcionalidad nueva → crear spec nueva.
- [ ] Si se agregaron herramientas o comandos nuevos → actualizar `AGENTS.md`.
- [ ] Mantener sincronizada la documentación en `docs/`.

### 3.2 Validación de Convenciones

- Respetar estrictamente el tipado en Python.
- Respetar la modularidad en JS vanilla (`api.js`, `state.js`, `ui.js`, `admin.js`, `main.js`).
- Respetar las estructuras de roles/perfiles en la base de datos.
- Verificar cambios con linters y pruebas antes de dar por finalizada una tarea.

### 3.3 Actualización Obligatoria Post-Cambio

- Si se añade un nuevo componente o cambio arquitectónico, actualizar `specs/`.
- Si se introducen nuevas herramientas o dependencias, actualizar `AGENTS.md`.
- Mantener sincronizada la documentación en `docs/`.

### 3.4 Uso Obligatorio de Skills y MCPs

**Skills por área de trabajo:**

| Área | Skill a consultar |
|------|-------------------|
| Backend Python / FastAPI | `anomalia-backend-skill` |
| Ansible / Infraestructura | `anomalia-ansible-skill` |
| Frontend Vanilla JS | `anomalia-frontend-validator` |
| Mobile Flutter / Android | `anomalia-flutter-mobile-skill` |
| Pipeline AIOps / Alertas | `anomalia-aiops-pipeline-skill` |

**MCPs disponibles:**

| MCP | Cuándo usarlo |
|-----|---------------|
| `postgres` | Antes de ejecutar queries a la BD para validar sintaxis y resultados esperados |
| `git` | Para verificar estado del repositorio, diffs y commits |
| `filesystem` | Para exploración segura de archivos dentro del proyecto |
| `context7` | Para consultar documentación actualizada de librerías y frameworks |

**Regla:** Antes de implementar cambios en un área específica, consultar el skill correspondiente. Antes de ejecutar queries a la BD, usar el MCP de postgres para validar.

### 3.5 Flujo de Documentación Obligatorio

**Antes de implementar:**
1. Leer la spec relevante según el tipo de cambio
2. Si no existe spec para la tarea → crearla ANTES de implementar

**Después de implementar:**
1. Actualizar la spec existente si el cambio afecta el comportamiento documentado
2. Crear spec nueva si es funcionalidad nueva
3. Actualizar `docs/` para reflejar cambios en la arquitectura o API
4. Actualizar `AGENTS.md` si se agregaron herramientas o comandos nuevos

### 3.6 Configuración HTTPS

El role `certs` materializa los certificados TLS en `/opt/anomalia/certs/`
(`fullchain.pem` y `privkey.pem`) y es **idempotente**: solo genera si no
existen. El hostname por defecto se parametriza en
`ansible-infra/roles/certs/defaults/main.yml`:

```yaml
certs_hostname: "anomalia.local"   # CN y SAN principal
certs_days: 3650                  # vigencia del autofirmado
```

Con certificado presente, el role `backend` despliega dos servicios:

| Servicio | Puerto host | TLS | Contenedor |
|---|---|---|---|
| `anomaliagw` | `80`, `8000` | no | `anomalia_gw` |
| `anomaliagw_tls` | `443` | sí | `anomalia_gw_tls` |

`FORCE_HTTPS=true` activa el middleware `enforce_https_redirect` en
`backend/app/main.py`, que redirige HTTP → HTTPS. **No redirige** `/metrics` ni
`/healthz` (vmagent scrapea el gateway en claro por `backend_ip:8000/metrics`),
ni peticiones cuyo Host sea `localhost`/`127.0.0.1`.

**Sin certificado el stack arranca igual en HTTP**: la plantilla
`docker-compose.yml.j2` omite `anomaliagw_tls` y `FORCE_HTTPS` queda en `false`.

Para pasar a producción, sustituir los dos archivos por los de una CA real
(Let's Encrypt) y redesplegar. El formato de entrada es idéntico, no requiere
cambios de código.

Detalle completo en `specs/007-https-gateway-and-tenant-access.md`.

### 3.7 Flujo de Repliegue Post-Cambio

Después de implementar un cambio de código (no documentación, specs o AGENTS.md), el usuario debe ejecutar manualmente:

```bash
cd ansible-infra && ansible-playbook -i inventory.ini destroy-infra.yml && ansible-playbook -i inventory.ini deploy-infra.yml
```

Esto destruye toda la infraestructura y la vuelve a levantar con los cambios aplicados. Requiere credenciales de sudo.

El `destroy-infra.yml` es agnóstico al motor de contenedores (detecta Docker/Podman y
Compose v1/v2 con los mismos facts que el deploy) y retira también el aislamiento L4 de
los puertos de lectura: unit `anomalia-victoria-firewall`, cadena iptables
`ANOMALIA_VICTORIA_READ` (con su salto en `INPUT`) y rich rules de firewalld. Las imágenes
y volúmenes se borran solo si pertenecen a los proyectos compose de Anomalia; las
imágenes base compartidas (`postgres`, `ollama`) y `/opt/anomalia/certs` se conservan.
Detalle en `specs/009-platform-support-and-prerequisites.md` §7.

**Nota:** El asistente NO debe ejecutar estos comandos automáticamente. El usuario es responsable de ejecutarlos cuando lo considere necesario. Los cambios solo en documentación (`docs/`, `specs/`, `AGENTS.md`) no requiren repliegue.

### 3.8 Verificación Obligatoria de Documentación

Antes de implementar cualquier cambio, verificar:
1. Leer la spec relevante según el tipo de cambio
2. Verificar que el cambio cumpla con la `constitution.md`
3. Seguir el checklist SSD de `AGENTS.md`
4. **Consultar el skill correspondiente al área de trabajo**

Después de implementar:
1. Actualizar la spec existente si el cambio afecta el comportamiento documentado
2. Crear spec nueva si es funcionalidad nueva
3. Actualizar `AGENTS.md` si se agregaron herramientas o comandos nuevos
4. Mantener sincronizada la documentación en `docs/`

### 3.9 Recordatorio Crítico para el Asistente

**ES OBLIGATORIO:** Antes de cada modificación de código, el asistente DEBE:
1. Usar la herramienta `skill` para cargar el skill correspondiente
2. Leer la spec relevante
3. Después de implementar, actualizar la spec

**NO MODIFICAR CÓDIGO SIN ANTES CARGAR EL SKILL CORRESPONDIENTE.**

### 3.10 Checklist de Auto-Verificación

Antes de cada respuesta donde modifique código, preguntarme:
- [ ] ¿Cargué el skill correspondiente?
- [ ] ¿Leí la spec relevante?
- [ ] ¿El cambio cumple con constitution.md?

Después de implementar:
- [ ] ¿Actualicé la spec correspondiente?
- [ ] ¿Actualicé AGENTS.md si fue necesario?
