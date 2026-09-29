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
7. **Secretos:** Prohibido hardcodear credenciales, API keys o tokens. Referenciar siempre por variable de entorno.

## Manejo de Secretos

Las credenciales **nunca** se escriben en un archivo versionado. Todo secreto se
referencia por variable de entorno.

| Contexto | Prohibido | Correcto |
|----------|-----------|----------|
| Config MCP / JSON | `"Authorization": "Bearer sk-real-..."` | `"Bearer {env:CONTEXT7_API_KEY}"` |
| Python | `DB_PASSWORD = "hunter2"` | `DB_PASSWORD = os.getenv("DB_PASSWORD")` |
| Ansible | `password: literal-en-yaml` | `password: "{{ vault_db_password }}"` o `lookup('env', ...)` |
| Templates | valores por defecto con secreto real | placeholders `change-me` explícitos |

### Gate automático

`.gitleaks.toml` + `.pre-commit-config.yaml` escanean cada commit. Para correrlo
a mano sobre todo el repo:

```bash
gitleaks dir .
gitleaks git .          # historial completo
```

Si el hook bloquea un commit y el hallazgo es legítimo, el bypass explícito es
`SKIP=gitleaks git commit`. No usar `--no-verify`: desactiva todos los hooks.

### Variable pendiente

`opencode.json` referencia `CONTEXT7_API_KEY` por entorno. Si no está definida,
el MCP de Context7 falla sin autenticar. Definir en el shell:

```bash
export CONTEXT7_API_KEY="ctx7sk-..."
```

### Gap conocido: passwords de baja entropía

gitleaks detecta credenciales de **alta entropía** y de **proveedor conocido**.
**No** detecta passwords débiles de diccionario. Los templates de
`ansible-infra/` contienen valores como `anomal_password`, `admin_password` y
`change-me-secret` que el escáner no marca por diseño.

Esto está registrado como riesgo aceptado, no como descuido. Si alguna vez se
mueven esos secretos a variables de entorno, la cobertura sube sin tocar el
gate. No agregar reglas que marquen esos paths salvo que primero se.externalicen
los valores: producirían allowlist permanente y falsa sensación de control.

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
