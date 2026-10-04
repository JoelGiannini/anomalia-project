# Constitución del Proyecto Anomalia (SSD Constitution)

## Preámbulo y Filosofía
Este documento establece las reglas arquitectónicas, estándares de desarrollo y principios rectores del proyecto **Anomalia**. Todas las contribuciones de código, refactorizaciones y adiciones de funcionalidades deben adherirse estrictamente a esta constitución bajo el paradigma **SSD (Specs Anchored Development)**.

---

## 1. Principios de Arquitectura

### 1.1 Multitenancy y Aislamiento Estricto
- Cada *tenant* (inquilino) debe contar con delimitación de aislamiento a nivel de cuenta (`account_id`), proyecto (`project_id`) y namespace de métricas/logs/trazas.
- Ninguna consulta o ingesta de telemetría debe mezclar datos entre inquilinos sin autorización explícita y validación RBAC.
- Las alertas asociadas a un tenant operan de forma aislada a través de su propia configuración de evaluación (`vmalert`) y notificación (`Alertmanager`).

### 1.2 Infraestructura como Código (IaC) e Idempotencia
- Todos los servicios del stack de observabilidad (VictoriaMetrics, VictoriaLogs, VictoriaTraces, Pyroscope, vmagent, vmauth, Alertmanager, vmalert, Parses) se despliegan y actualizan mediante roles y playbooks de **Ansible**.
- La base de datos (`infrastructure_nodes`) actúa como inventario fuente de verdad para el aprovisionamiento de nodos dinámicos.
- Los playbooks y tareas deben ser estrictamente idempotentes.

### 1.3 Pipeline AIOps Confiable y No Bloqueante
- El webhook de ingesta de alertas desde Alertmanager hacia el backend FastAPI debe procesarse de manera asíncrona o en background tasks para no saturar al notificador.
- El enriquecimiento y diagnóstico de alertas mediante Inteligencia Artificial (Ollama / LLMs locales o remotos) debe manejar timeouts, reintentos y mecanismos de fallback en caso de indisponibilidad del modelo.
- La distribución de alertas enriquecidas debe despacharse de forma concurrente hacia la interfaz Web y los dispositivos móviles Android vía notificaciones push.

---

## 2. Convenciones de Código y Estándares Técnicos

### 2.1 Backend (Python / FastAPI)
- **Tipado Estricto:** Todo endpoint y función interna debe contar con *type hints* completos.
- **Validación de Datos:** Uso riguroso de esquemas **Pydantic** para validar entradas y salidas.
- **Seguridad y RBAC:** Cada endpoint administrativo o de infraestructura debe protegerse con las dependencias de inyección (`Depends(verify_admin_token)`, `Depends(verify_profile_access)`).
- **Acceso a Datos:** Respetar la integridad referencial en PostgreSQL. Las migraciones y alteraciones de esquema deben documentarse y versionarse (soporte futuro con Alembic).

### 2.2 Frontend Web
- Mantener una arquitectura ligera, modular y sin dependencias superfluas en JavaScript vanilla (`js/state.js`, `js/api.js`, `js/ui.js`, `js/admin.js`).
- Toda interacción con el backend debe realizarse a través del cliente API centralizado respetando la gestión de tokens JWT/OIDC en almacenamiento local.

### 2.3 Aplicación Móvil (Flutter / Android)
- Arquitectura limpia y desacoplada respetando los lineamientos de Material Design.
- Autenticación segura mediante flujos OIDC nativos (`flutter_appauth`, `app_links`).
- Gestión de estado transparente para el listado de alertas y recepción de notificaciones en segundo plano.

### 2.4 Visualización y Dashboards (Parses)
- El componente **Parses** es responsable de procesar, normalizar y exponer la telemetría para la renderización de dashboards dentro de la plataforma. Cualquier cambio en formatos de ingesta debe mantener compatibilidad con este módulo.

---

## 3. Protocolo SSD (Specs Anchored Development)

1. **Especificación Antes de la Implementación:**
   - Ninguna funcionalidad significativa o cambio arquitectónico puede implementarse sin una especificación técnica formal anclada en `specs/`.
2. **Revisión y Aprobación:**
   - Todo cambio debe ser evaluado contra las especificaciones vigentes y requerir la confirmación del usuario.
3. **Sincronización Continua del Ecosistema:**
   - Tras cada cambio exitoso aprobado por el usuario, es obligatorio:
     - Actualizar o crear la especificación técnica correspondiente en `specs/`.
     - Actualizar el archivo `AGENTS.md` si se modificaron herramientas, comandos, librerías o directrices de entorno.
     - Actualizar la documentación técnica en `docs/` para mantener sincronizado el portal MkDocs/GitBook.

## 4. Prevención de Alucinaciones y Control Estricto (Anti-Hallucination Policy)
- **Cero Suposiciones:** Está terminantemente prohibido inventar librerías, funciones, endpoints o tablas que no existan en el proyecto o en las dependencias declaradas (`requirements.txt`, `pubspec.yaml`).
- **Alcance Atómico:** Las modificaciones deben limitarse estrictamente al archivo y líneas solicitadas por el usuario. No refactorizar código adyacente a menos que sea un requerimiento explícito.
- **Temperatura y Determinismo:** Las operaciones de código deben priorizar la máxima precisión lógica y literalidad.
- **Validación Obligatoria:** Todo cambio de código debe verificarse mediante linters y pruebas antes de darse por finalizado.
- **Prohibición de Secretos en el Repositorio:** Está terminantemente prohibido versionar credenciales, API keys, tokens o claves privadas. Todo secreto se referencia por variable de entorno (`{env:...}` en JSON, `os.getenv()` en Python, `lookup('env', ...)` en Ansible). El escaneo se automatiza con `gitleaks` vía `pre-commit` (ver `specs/006-secret-scanning-gate.md`); la allowlist es por path, nunca por valor.
- **Prohibición Absoluta de Commit / Push Autónomo:** Está terminantemente prohibido que la IA ejecute comandos `git commit`, `git push` o altere repositorios remotos de manera autónoma. Cualquier operación de versionado o publicación en control de versiones requiere aprobación explícita y manual del usuario.
