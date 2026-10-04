# Spec 002: Aprovisionamiento de Tenants y Alertmanager por Nodo

## 1. Objetivo
Permitir que al dar de alta o actualizar un Tenant en el sistema, se pueda especificar si requiere alertas (`has_alerts`) y sobre qué nodo de la infraestructura (`infrastructure_nodes`) se desplegará o gestionará su instancia de `vmalert`.

## 2. Modelo de Datos y Relaciones
- La tabla `tenants` almacena los atributos del tenant (nombre, tipo, account_id, project_id, port, etc.).
- Se relaciona con la tabla `infrastructure_nodes` para determinar la ubicación física/lógica del nodo encargado de la evaluación de alertas.

### 2.1 Concesión de acceso (implementado en Spec 007)

El alta de un tenant **no** implica acceso automático para ningún usuario. El
acceso es la unión de asignación directa (`user_tenants`) y asignación por rol
(`role_tenants` a través de `user_roles`).

Consecuencia operativa: al crear un tenant hay que insertar explícitamente las
filas en `role_tenants` para los roles que deban verlo, incluyendo `admin`. De lo
contrario el tenant existe pero es invisible para todos, incluido el
administrador. No hay bypass por rol en el código.

## 3. Orquestación con Ansible
- El backend disparará de forma controlada la ejecución de playbooks de Ansible para configurar y recargar el servicio `vmalert` apuntando al Alertmanager correspondiente del nodo seleccionado.

## 4. Estado
- **Implementado**: concesión de acceso, `verify_tenant_access`.
- **Pendiente**: `has_alerts`, `vmalert_node_id` y `vmalert_port` en `tenants`;
  Instancias de vmalert por tenant; integración con el inventario.
