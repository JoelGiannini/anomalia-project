---
name: anomalia-security-skill
description: Skill especializado en seguridad, RBAC, autenticación JWT/OIDC y protección de endpoints. Use cuando se modifique código relacionado con seguridad.
---

# Anomalia Security Standards

## Reglas Obligatorias

1. **Autenticación:** Todos los endpoints deben requerir autenticación JWT/OIDC válida.
2. **RBAC:** Cada endpoint administrativo debe verificar roles y perfiles del usuario.
3. **Protección de Datos:** Las contraseñas deben almacenarse con hash (bcrypt). Nunca en texto plano.
4. **HTTPS:** En producción, todos los endpoints deben usar HTTPS.
5. **Validación de Entrada:** Validar y sanitizar todas las entradas del usuario.
6. **Manejo de Errores:** No exponer información sensible en mensajes de error.

## Endpoints Protegidos

| Endpoint | Protección |
|----------|------------|
| `/api/v1/admin/*` | `Depends(verify_admin_token)` o `Depends(verify_profile_access)` |
| `/api/infrastructure/*` | `Depends(verify_admin_token)` |
| `/api/v1/auth/*` | Autenticación JWT/OIDC |

## Roles y Perfiles

- **Roles:** `admin`, `viewer`, `auditor`, `tenant_manager`, `infra_manager`, `user_manager`, `role_manager`
- **Perfiles:** `admin`, `users_manager`, `roles_manager`, `profile_manager`, `access_metrics`, `access_logs`, `access_traces`, `access_Continuous_Profiling`, `access_alerts`, `tenants_manager`

## Consideraciones de Seguridad

- **Tokens JWT:** Verificar firma y expiración
- **Contraseñas:** Usar bcrypt con salt
- **SQL Injection:** Usar consultas parametrizadas (psycopg2)
- **XSS:** Sanitizar salida en el frontend
- **CSRF:** Implementar protección CSRF para formularios
