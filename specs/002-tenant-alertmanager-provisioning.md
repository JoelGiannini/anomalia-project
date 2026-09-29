# Spec 002: Aprovisionamiento de Tenants y Alertmanager por Nodo

## 1. Objetivo
Permitir que al dar de alta o actualizar un Tenant en el sistema, se pueda especificar si requiere alertas (`has_alerts`) y sobre qué nodo de la infraestructura (`infrastructure_nodes`) se desplegará o gestionará su instancia de `vmalert`.

## 2. Modelo de Datos y Relaciones
- La tabla `tenants` almacena los atributos del tenant (nombre, tipo, account_id, project_id, port, etc.).
- Se relaciona con la tabla `infrastructure_nodes` para determinar la ubicación física/lógica del nodo encargado de la evaluación de alertas.

## 3. Orquestación con Ansible
- El backend disparará de forma controlada la ejecución de playbooks de Ansible para configurar y recargar el servicio `vmalert` apuntando al Alertmanager correspondiente del nodo seleccionado.
