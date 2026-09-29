# Arquitectura General

Anomalia está diseñada bajo una arquitectura modular y multitenant orientada a microservicios e infraestructura distribuida.

## Componentes del Sistema
1. **Backend API:** FastAPI (Python) para lógica de negocio, RBAC, gestión de tenants y webhooks.
2. **Base de Datos:** PostgreSQL 15 para persistencia transaccional.
3. **Observabilidad:** VictoriaMetrics, VictoriaLogs, VictoriaTraces, Pyroscope, vmalert, Alertmanager, Parser.
4. **Interfaces:** Panel Web Vanilla JS y App Móvil Flutter.
