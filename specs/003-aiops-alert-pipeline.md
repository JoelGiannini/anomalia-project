# Spec 003: Pipeline de Alertas y Análisis con IA (AIOps)

## 1. Flujo de Alertas
1. **Evaluación:** `vmalert` evalúa las reglas de métricas del tenant y dispara la alerta hacia `Alertmanager`.
2. **Webhook:** `Alertmanager` despacha el payload de la alerta mediante un webhook HTTP POST hacia el **Backend FastAPI**.
3. **Análisis IA:** El backend procesa la alerta, extrae el contexto y consulta al proveedor de IA configurado para obtener un diagnóstico de causa raíz y posibles soluciones.
4. **Distribución:** La alerta enriquecida se almacena y se transmite en tiempo real hacia la interfaz Web y la aplicación móvil Android para notificar al usuario.
