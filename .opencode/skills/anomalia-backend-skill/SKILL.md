---
name: anomalia-backend-skill
description: Skill especializado para trabajar con el backend FastAPI, modelos Pydantic, PostgreSQL y lógica RBAC del proyecto Anomalia. Use cuando se modifique código en backend/app/.
---

# Anomalia Backend Standards

## Reglas Obligatorias

1. **Tipado Estricto:** Todo endpoint y función interna debe contar con type hints completos.
2. **Validación de Datos:** Uso riguroso de esquemas Pydantic para validar entradas y salidas.
3. **Seguridad y RBAC:** Cada endpoint administrativo debe protegerse con `Depends(verify_admin_token)` o `Depends(verify_profile_access)`.
4. **Acceso a Datos:** Respetar la integridad referencial en PostgreSQL. Las migraciones deben documentarse y versionarse.
5. **Manejo de Errores:** Usar `HTTPException` con códigos de estado apropiados (400, 401, 403, 404, 500).
6. **Async/Await:** Usar `async def` para endpoints que realizan I/O (consultas a BD, llamadas HTTP).
7. **Logging:** Usar `print()` o `logging` para depuración, nunca dejar prints de debug en producción.

## Estructura de Routers

- `auth_router.py` — Autenticación y gestión de sesiones
- `admin_router.py` — Administración (usuarios, roles, perfiles, tenants, infra)
- `infra_router.py` — Gestión de infraestructura (nodos, playbooks)
- `oidc.py` — Integración OIDC

## Convenciones de Código

- Nombres de funciones en snake_case
- Nombres de clases en PascalCase
- Constantes en UPPER_SNAKE_CASE
- Documentar funciones complejas con docstrings
