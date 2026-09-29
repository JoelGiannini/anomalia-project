---
name: anomalia-flutter-mobile-skill
description: Skill especializado en la app móvil Flutter (Android/iOS), autenticación OIDC y recepción de notificaciones de alertas. Use cuando se modifique código en mobile/.
---

# Anomalia Flutter Mobile Standards

## Reglas Obligatorias

1. **Autenticación OIDC:** Usar `flutter_appauth` y `app_links` para flujos OIDC nativos.
2. **Notificaciones Push:** Implementar recepción de notificaciones en segundo plano.
3. **Gestión de Estado:** Usar Provider o Riverpod para gestión de estado. No usar setState directamente en widgets complejos.
4. **Manejo de Errores:** Manejar errores de red, timeouts y respuestas inválidas del backend.
5. **UI Responsiva:** Diseñar pantallas que se adapten a diferentes tamaños de pantalla.
6. **Accesibilidad:** Respetar las guías de accesibilidad de Material Design.

## Estructura del Proyecto

```
lib/
  main.dart              # Punto de entrada
  models/                # Modelos de datos
  screens/               # Pantallas de la app
  widgets/               # Widgets reutilizables
  services/              # Servicios (API, notificaciones)
  utils/                 # Utilidades (constantes, helpers)
```

## Convenciones de Código

- Nombres de clases en PascalCase
- Nombres de variables y funciones en camelCase
- Constantes en lowerCamelCase
- Usar `const` para widgets inmutables

## Dependencias Clave

- `flutter_appauth` — Autenticación OIDC
- `app_links` — Enlaces profundos
- `http` — Llamadas HTTP
- `shared_preferences` — Almacenamiento local
