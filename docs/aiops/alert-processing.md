# Pipeline de Alertas y AIOps

El flujo de procesamiento automatizado de anomalías opera de la siguiente manera:
1. **vmalert** evalúa las reglas de métricas del tenant.
2. **Alertmanager** notifica vía webhook al backend FastAPI.
3. El **Backend** procesa la alerta y consulta al modelo de IA para diagnóstico.
4. Se distribuye la alerta enriquecida al panel Web y a la App Android.
