# ADR-0006: Mapa en tiempo real con React + MapLibre GL en el mismo repositorio

- **Fecha**: 2026-10-15
- **Estado**: Aceptada (proveedor de tiles: OpenFreeMap, ver ADR-0010)

## Contexto
El mapa en vivo es la parte más visible del proyecto. El plan inicial lo dejaba para otro
repositorio, lo que retrasa tener algo demostrable.

## Decisión
- Frontend en `web/` dentro de este repositorio (monorepo): **React + TypeScript + Vite**.
- Mapa con **MapLibre GL JS** (open source, WebGL).
- Los buques se dibujan como una **capa GeoJSON**, no como markers DOM, para escalar a miles de
  puntos con buen rendimiento.
- Proveedor de tiles configurable por `VITE_MAP_STYLE_URL`. Candidatos: OpenFreeMap (sin key) o
  MapTiler (plan gratuito con key restringida por dominio). Decidir en Fase 4 tras revisar sus
  términos de uso.
- **No** usar los tiles de `tile.openstreetmap.org` en producción: su política de uso no permite
  aplicaciones con tráfico continuo.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Leaflet | más simple, pero con markers DOM se degrada con cientos de buques en movimiento |
| Mapbox GL JS | licencia propietaria desde v2 y requiere cuenta de pago a cierto uso |
| deck.gl | potente, pero excesivo para este volumen; se puede añadir sobre MapLibre si hace falta |
| Repo separado | retrasa la demo y complica versionar el contrato del WebSocket |

## Consecuencias
- El CI incluye un job de frontend (lint, typecheck, tests, build).
- Si se usa una key de tiles en el frontend, es pública por naturaleza: debe estar restringida
  por dominio en el panel del proveedor.
