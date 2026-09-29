---
name: anomalia-ansible-skill
description: Skill especializado para la gestión de playbooks, inventarios y roles de Ansible para el despliegue de la infraestructura de observabilidad. Use cuando se modifique código en ansible-infra/.
---

# Anomalia Ansible Standards

## Reglas Obligatorias

1. **Idempotencia:** Todas las tasks deben ser idempotentes. Ejecutar múltiples veces no debe causar efectos secundarios.
2. **Roles Desacoplados:** Cada rol debe ser independiente y reutilizable. No acoplar lógica de un rol a otro.
3. **Variables en defaults/main.yml:** Las variables por defecto deben definirse en `roles/<role>/defaults/main.yml`.
4. **Templates Jinja2:** Usar templates `.j2` para archivos de configuración. No hardcodear valores en los playbooks.
5. **Inventario Dinámico:** Generar inventarios dinámicamente desde la BD cuando sea posible.
6. **Manejo de Errores:** Usar `ignore_errors: yes` solo cuando sea necesario y documentar por qué.
7. **Tags:** Usar tags para permitir ejecución parcial de playbooks (ej. `--tags backend`).

## Estructura de Roles

```
roles/
  <role>/
    tasks/main.yml      # Tasks principales
    handlers/main.yml   # Handlers (restart, reload)
    templates/          # Templates Jinja2
    defaults/main.yml   # Variables por defecto
    vars/main.yml       # Variables del rol
```

## Convenciones de Nombres

- Nombres de roles en snake_case
- Nombres de tasks descriptivos (ej. "Crear directorio de datos")
- Nombres de variables con prefijo del rol (ej. `vmstorage_path`)

## Playbooks Principales

- `deploy-infra.yml` — Despliegue completo de la infraestructura
- `destroy-infra.yml` — Destrucción completa de la infraestructura
- `add-node.yml` — Alta de nuevo nodo (onboarding + reconfiguración)
- `install-binaries.yml` — Actualización de binarios
