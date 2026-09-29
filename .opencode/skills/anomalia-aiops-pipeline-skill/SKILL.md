---
name: anomalia-aiops-pipeline-skill
description: Skill especializado en la integración de webhooks de Alertmanager, procesamiento de alertas y análisis de causa raíz con IA. Use cuando se modifique código relacionado con el pipeline AIOps.
---

# Anomalia AIOps Pipeline Standards

## Reglas Obligatorias

1. **Webhooks No Bloqueantes:** El webhook de Alertmanager debe procesarse de manera asíncrona o en background tasks.
2. **Manejo de Errores:** El pipeline debe manejar timeouts, reintentos y mecanismos de fallback en caso de indisponibilidad del modelo de IA.
3. **Distribución Concurrente:** Las alertas enriquecidas deben despacharse de forma concurrente hacia la Web y la app móvil.
4. **Logging:** Registrar cada etapa del pipeline (recepción, análisis, distribución) para facilitar el debugging.
5. **Validación:** Validar el payload de Alertmanager antes de procesarlo.

## Flujo del Pipeline

1. **Recepción:** Alertmanager envía webhook al backend FastAPI
2. **Validación:** El backend valida el payload y extrae información relevante
3. **Análisis:** El backend consulta al modelo de IA para obtener diagnóstico
4. **Almacenamiento:** La alerta enriquecida se guarda en la BD
5. **Distribución:** La alerta se envía a la Web y a la app móvil

## Componentes

- **Alertmanager** — Evalúa reglas y envía webhooks
- **Backend FastAPI** — Recibe webhooks, procesa alertas, consulta IA
- **IA (Ollama/LLM)** — Analiza alertas y genera diagnóstico
- **Web (Vanilla JS)** — Muestra alertas en tiempo real
- **App Móvil (Flutter)** — Recibe notificaciones push

## Manejo de Errores

- **Timeout de IA:** Si el modelo de IA no responde en 30 segundos, retornar alerta sin enriquecimiento
- **Reintentos:** Reintentar hasta 3 veces con backoff exponencial
- **Fallback:** Si la IA no está disponible, retornar alerta con mensaje de error
