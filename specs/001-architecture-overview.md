# Spec 001: Arquitectura General y Multitenancy

## 1. Resumen
La plataforma Anomalia es un sistema de observabilidad multitenant enfocado en la gestión de infraestructura, telemetría (métricas, logs, trazas, profiling) y análisis inteligente de alertas mediante IA (AIOps).

## 2. Componentes Principales
- **Backend FastAPI (`/backend`):** API central que maneja la autenticación, RBAC, gestión de tenants, infraestructura y recepción de alertas.
- **Base de Datos PostgreSQL:** Almacena usuarios, roles, perfiles, asignaciones, nodos de infraestructura y configuración de tenants.
- **Stack de Observabilidad (`/ansible-infra`):** VictoriaMetrics, VictoriaLogs, VictoriaTraces, Pyroscope, vmagent, vmauth, Alertmanager, vmalert y Parser.
- **Frontend Web (`/backend/frontend`):** Panel de administración y visualización basado en JavaScript vanilla.
- **App Móvil (`/mobile`):** Aplicación Flutter (Android/iOS) para recepción de alertas push y supervisión.
