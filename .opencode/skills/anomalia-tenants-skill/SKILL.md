---
name: anomalia-tenants-skill
description: Skill especializado en la gestión de tenants, namespaces y configuración de alertas por tenant. Use cuando se modifique código relacionado con tenants.
---

# Anomalia Tenants Standards

## Reglas Obligatorias

1. **Aislamiento Estricto:** Cada tenant debe tener delimitación de aislamiento a nivel de cuenta (`account_id`), proyecto (`project_id`) y namespace de métricas/logs/trazas.
2. **Sin Mezcla de Datos:** Ninguna consulta o ingesta de telemetría debe mezclar datos entre tenants sin autorización explícita.
3. **Configuración por Tenant:** Las alertas asociadas a un tenant operan de forma aislada a través de su propia configuración de evaluación (`vmalert`) y notificación (`Alertmanager`).
4. **Validación:** Validar que el usuario tiene acceso al tenant antes de realizar operaciones.

## Estructura de Datos

- `tenants` — Tabla de tenants (id, name, type, account_id, project_id, environment, port, description)
- `user_tenants` — Relación usuarios-tenants (user_id, tenant_id)
- `role_tenants` — Relación roles-tenants (role_id, tenant_id)

## Flujo de Alta de Tenant

1. **Validación:** Verificar que el usuario tiene el perfil `tenants_manager`
2. **Inserción:** Insertar en tabla `tenants`
3. **Configuración:** Si requiere alertas, configurar `vmalert` y `Alertmanager` para el tenant
4. **Asignación:** Asignar usuarios y roles al tenant

## Consideraciones de Seguridad

- **RBAC:** Solo usuarios con perfil `tenants_manager` pueden crear/modificar tenants
- **Aislamiento:** Los datos de un tenant no deben ser accesibles desde otro tenant
- **Auditoría:** Registrar todas las operaciones sobre tenants
