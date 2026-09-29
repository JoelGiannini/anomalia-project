---
name: anomalia-frontend-validator
description: Valida de forma estricta las convenciones de código front-end Vanilla JS modular, manejo de estado centralizado, integración API, autenticación OIDC y estilos corporativos. Use cuando se modifique código en backend/frontend/.
---

# Anomalia Frontend Standards (Vanilla JS Modular)

## Reglas Obligatorias y Restricciones Estrictas
1. **Cero Inventos / Estricta Adherencia:** Está terminantemente prohibido introducir frameworks (como React, Vue, Svelte) o librerías externas que no estén declaradas en el proyecto. Todo el frontend debe resolverse con JavaScript Vanilla puro, HTML5 y CSS3.
2. **Modularidad Existente:** Respetar estrictamente los módulos vigentes:
   - `api.js`: Centraliza peticiones HTTP.
   - `state.js`: Gestión de estado.
   - `ui.js`: Renderizado y manipulación del DOM.
   - `admin.js` / `main.js`: Controladores de vistas.
3. **Manejo de Autenticación & Tokens:** Toda llamada a endpoints protegidos debe adjuntar correctamente el token JWT/OIDC recuperado desde el almacenamiento local o el state manager (`state.js`).
4. **Estilos Corporativos:** Utilizar únicamente las clases y variables CSS definidas en `styles.css`. No crear estilos en línea arbitrarios.
5. **Resguardo UI Obligatorio:** Toda carga de datos asíncrona desde la API debe implementar estados visuales explícitos:
   - Indicador de carga (`loading`).
   - Manejo de excepciones / errores de red (alertas visuales al usuario).
   - Estados vacíos (`empty state`) cuando no existan registros (ej. tenants o nodos de infraestructura).
