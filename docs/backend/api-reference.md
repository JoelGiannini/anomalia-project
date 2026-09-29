# Referencia de API Backend

El backend expone endpoints RESTful protegidos por autenticación OIDC/JWT y control de acceso basado en roles y perfiles.

## Routers Principales
- `/api/auth`: Autenticación y gestión de sesiones.
- `/api/admin`: Gestión de usuarios, roles, perfiles y tenants (`tenants_manager`).
- `/api/infrastructure`: Gestión de nodos de infraestructura (`infrastructure_nodes`).
- `/api/v1/tenants`: Endpoints puente para consulta de tenants del usuario.
