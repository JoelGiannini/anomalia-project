# Spec 004: Control de Acceso Basado en Roles y Perfiles (RBAC)

## 1. Modelo de Seguridad
- El sistema utiliza un esquema robusto basado en **Roles** (`admin`, `viewer`, `auditor`, `tenant_manager`, `infra_manager`, `user_manager`, `role_manager`) y **Perfiles de Acceso** (`Metrics Profile`, `Logs Profile`, `Traces Profile`, `Profiling Profile`, `Alerts Profile`, `Tenants Manager Profile`).
- Los endpoints del backend validan estrictamente los tokens JWT y los perfiles asociados mediante dependencias FastAPI (`verify_admin_token`, `verify_profile_access`).
