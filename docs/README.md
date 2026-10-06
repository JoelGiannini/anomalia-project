# Documentación Oficial de Anomalia

Bienvenido a la documentación técnica oficial de **Anomalia**, la plataforma multitenant de observabilidad e inteligencia artificial aplicada a la infraestructura (**AIOps**).

> **Plataforma enterprise de observabilidad unificada** con aislamiento estricto por tenant, control de acceso basado en perfiles, integración con el ecosistema VictoriaMetrics, y diagnósticos automatizados mediante LLMs locales y remotos.

---

## 🗺️ Mapa de Navegación

| Sección | Descripción | Acceso Directo |
| :--- | :--- | :--- |
| **Arquitectura General** | Visión modular, multitenancy, gateway HTTPS y proxy de consolas | [Ver Arquitectura](./architecture/overview.md) |
| **Tenants Internos** | Reglas canónicas inmutables y bootstrap *always-on* (`is_internal`) | [Ver Tenants Internos](./architecture/internal-tenants.md) |
| **Referencia de API** | Endpoints REST, RBAC, webhooks, sync de reglas y chat IA | [Ver API Reference](./backend/api-reference.md) |
| **Pipeline AIOps & Chat** | Proveedores de IA, analizadores y restricciones por contexto | [Ver AIOps & Chat](./backend/aiops-and-chat.md) |
| **Infraestructura IaC** | Despliegue con Ansible, soporte multiplataforma y comandos destroy | [Ver Despliegue](./infrastructure/ansible-deployment.md) |
| **Aplicación Móvil** | App Flutter, autenticación OIDC y recepción de alertas | [Ver App Móvil](./mobile/flutter-app.md) |

---

## 🏗️ Arquitectura General del Sistema

```mermaid
graph TD
    subgraph Client ["Clientes y Consolas"]
        Web[Panel Web Vanilla JS]
        App[App Móvil Flutter]
    end

    subgraph Gateway ["Gateway HTTPS / Nginx (Port 443)"]
        GW[Anomalia Gateway TLS]
    end

    subgraph Backend ["Backend FastAPI & Workers"]
        API[FastAPI Core & Routers]
        TW[TenantWorker (30s)]
        VW[VmalertWorker (30s)]
        AI[AI Chat Engine (Strict Contexts)]
    end

    subgraph DB ["Base de Datos PostgreSQL (SSOT)"]
        PG[(PostgreSQL 15)]
    end

    subgraph Infra ["Nodos de Infraestructura (Ansible)"]
        VMA[vmagent]
        VMAlert[vmalert per-tenant (1:1)]
        AM[Alertmanager]
    end

    Web -->|JWT / HTTPS| GW
    App -->|OIDC Token| GW
    GW --> API
    API --> PG
    TW -->|Provision Tenants & Parses| PG
    VW -->|Ansible Playbook sync| Infra
    API -->|Context Security Guard| AI
```

---

## 🚀 Características Principales

- **Multitenancy Estricto:** Aislamiento de cuentas (`account_id`), proyectos (`project_id`) y namespaces corporativos de métricas, trazas, logs y perfiles.
- **Instancias `vmalert` 1:1:** Cada tenant activo puede desplegar su propia instancia dedicada de evaluación de alertas con balanceo automático por menor carga en los nodos de infraestructura.
- **Tenants de Control Interno:** Supervisión robusta y nativa del estado general del stack mediante reglas canónicas inmutables.
- **Consolas Seguras via Tickets:** Acceso transparente a las interfaces de VictoriaMetrics, VictoriaTraces, VictoriaLogs, Pyroscope y Parses a través de un sistema de tickets deslizantes con cifrado y cookie `HttpOnly`.
- **AIOps & Chat Contextual:** Diagnóstico automatizado de incidentes y chat interactivo con restricciones estrictas de ámbito para evitar fugas de contexto entre tenants.
- **Automatización Ansible idempotente:** Despliegue de infraestructura agnóstico y tolerante a fallos, preparado para Debian/Ubuntu y RHEL/Rocky Linux.
