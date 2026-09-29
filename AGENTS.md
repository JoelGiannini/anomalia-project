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
  - Alertas y Procesamiento: Alertmanager, Parser de Dashboards, Pyroscope.

---

## 2. Comandos de Entorno, Compilación y Testing

### 2.1 Backend (FastAPI & Base de Datos)
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

### 2.2 Infraestructura (Ansible)
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

### 2.3 Aplicación Móvil (Flutter)
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

La aplicación soporta HTTPS con certificados de confianza del usuario. Para habilitar:

1. Colocar los certificados en `/opt/anomalia/certs/`:
   - `fullchain.pem` - certificado completo
   - `privkey.pem` - clave privada

2. Reiniciar el contenedor:
   ```bash
   docker restart anomalia_gw
   ```

Si no se proporcionan certificados, la aplicación se levanta por defecto en HTTP (puerto 8000).

### 3.7 Flujo de Repliegue Post-Cambio

Después de implementar un cambio de código (no documentación, specs o AGENTS.md), el usuario debe ejecutar manualmente:

```bash
cd ansible-infra && ansible-playbook -i inventory.ini destroy-infra.yml && ansible-playbook -i inventory.ini deploy-infra.yml
```

Esto destruye toda la infraestructura y la vuelve a levantar con los cambios aplicados. Requiere credenciales de sudo.

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
