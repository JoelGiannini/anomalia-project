# Despliegue de Infraestructura

El despliegue se gestiona íntegramente mediante **Ansible** (`ansible-infra/`).

## Comandos Clave
- **Validación de sintaxis:**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini deploy-infra.yml --syntax-check
  ```
- **Despliegue completo:**
  ```bash
  cd ansible-infra
  ansible-playbook -i inventory.ini deploy-infra.yml
  ```
