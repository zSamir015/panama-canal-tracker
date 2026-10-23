# ADR-0010: Tiles del mapa con OpenFreeMap

- **Fecha**: 2026-10-23
- **Estado**: Aceptada
- **Completa**: ADR-0006 (dejaba el proveedor de tiles para la Fase 4)

## Contexto
ADR-0006 eligió MapLibre GL y dejó dos candidatos para los tiles: OpenFreeMap (sin key) y
MapTiler (plan gratuito con key restringida por dominio). La tarea 4.3 (#67) necesita uno.
Revisión del 2026-10-23 (`https://openfreemap.org`, `https://openfreemap.org/tos/`):

- **OpenFreeMap**: instancia pública gratuita, sin límite de vistas ni de peticiones, sin
  registro, sin keys y sin cookies. Permite uso comercial. Exige atribución
  ("© OpenMapTiles, Data from OpenStreetMap"), que el estilo ya declara y MapLibre muestra sola.
  Se ofrece "as-is", sin garantías, y puede cambiar o desaparecer sin aviso.
- **MapTiler**: SLA y más estilos, pero necesita cuenta, una key que acaba en el JavaScript público
  (hay que restringirla por dominio en su panel) y una cuota mensual que la demo podría agotar.

## Decisión
- Estilo por defecto: `https://tiles.openfreemap.org/styles/liberty` (`DEFAULT_MAP_STYLE_URL` en
  `web/src/config.ts`). `VITE_MAP_STYLE_URL` lo sustituye sin tocar código.
- No se guarda ninguna key de tiles en el frontend ni en el repositorio.
- Los iconos de los buques se generan en el código (SDF) en vez de ir en un sprite propio, así que
  el estilo se usa tal cual.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| MapTiler | cuenta, key pública que hay que restringir y cuota; nada de eso hace falta para la demo |
| `tile.openstreetmap.org` | su política de uso no permite tráfico continuo de una aplicación (ADR-0006) |
| Tiles propios (Planetiler + servidor) | más infraestructura que mantener que todo el resto de la demo |

## Consecuencias
- Si OpenFreeMap cae, el mapa se queda sin fondo, pero los buques siguen llegando por `/ws/live`.
  El plan B es cambiar `VITE_MAP_STYLE_URL` (otro proveedor o tiles propios) y recompilar.
- La CSP de la 4.7 tiene que permitir `https://tiles.openfreemap.org` en `connect-src` (estilo,
  tiles, glifos y sprites) e `img-src`, y `worker-src blob:` para los workers de MapLibre.
