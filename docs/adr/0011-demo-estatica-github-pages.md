# ADR-0011: Demo estática en GitHub Pages

- **Fecha**: 2026-10-25
- **Estado**: Aceptada

## Contexto
La tarea 4.7 del roadmap pedía desplegar la aplicación en un VPS con compose, reverse proxy, TLS
y firewall. Sin embargo, el objetivo real de la Fase 4 es tener una demo visible para el
portafolio: un mapa con buques moviéndose por el Canal de Panamá.

Un VPS implica coste mensual, mantenimiento de infraestructura, certificados TLS, actualizaciones
de seguridad del SO y monitorización. Para una demo de portafolio no es necesario.

Además, ADR-0008 prohíbe exponer datos de AISStream sin sesión autenticada. La demo pública
necesita funcionar sin backend y sin login.

## Decisión
Se sustituye el VPS por una **demo estática en GitHub Pages** que:

1. Se compila con `VITE_DEMO=true`, que activa un modo demo en el frontend.
2. En modo demo, la app **salta el login** y reproduce un archivo JSON pregrabado con posiciones
   de buques generadas por `scripts/ais_simulator.py` (~30 segundos en bucle).
3. Muestra una etiqueta permanente «⚠ Datos simulados» para evitar confusión con datos reales.
4. **No usa datos de AISStream** en ningún momento, cumpliendo ADR-0008.
5. Se despliega con un workflow de GitHub Actions (`pages.yml`) en cada push a `main`.

El build normal (sin `VITE_DEMO`) y los tests existentes no se modifican.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| VPS con compose + reverse proxy | Coste mensual, mantenimiento continuo, innecesario para portafolio |
| Vercel / Netlify | Otro servicio externo; Pages ya está integrado en GitHub |
| Demo con datos de AISStream en tiempo real | Prohibido por ADR-0008 sin sesión autenticada |
| Demo con backend en un free tier (Render, Fly) | Tiempos de arranque en frío, límites de horas, se apaga por inactividad |

## Consecuencias
- La demo es gratuita, permanente y sin mantenimiento de infraestructura.
- Solo muestra datos simulados: nadie puede confundirla con un servicio de datos AIS reales.
- El dueño del repo debe activar Pages en Settings → Pages → Source: GitHub Actions.
- URL de la demo: `https://zsamir015.github.io/panama-canal-tracker/`.
- La tarea 4.9 (GIF y enlace en el README) puede referenciar esta URL directamente.
- Si en el futuro se quiere desplegar la aplicación completa (con backend y datos reales), se
  puede hacer en un VPS o cloud como decisión independiente, sin afectar la demo de Pages.
