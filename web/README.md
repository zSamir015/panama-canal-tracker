# web/ — Mapa en tiempo real

Frontend del proyecto (Fase 4 del roadmap, ADR-0006): React + TypeScript (`strict`) + Vite.
Pide iniciar sesión (ADR-0008), abre `/ws/live` y pinta los buques del viewport en un mapa
MapLibre GL como una capa GeoJSON: flecha girada según el rumbo, color según el tipo de buque.

## Requisitos

Node `^22.22.2`, `^24.15.0` o `>=26` (lo que admiten Vite, Vitest y jsdom; ver `engines` en
`package.json`).

## Comandos

```bash
cd web
npm ci                 # instala exactamente lo de package-lock.json
npm run dev            # servidor de desarrollo en http://localhost:5173 (proxy de /api y /ws a :8000)
npm run lint           # ESLint con reglas que usan los tipos; 0 avisos permitidos
npm run format:check   # Prettier (npm run format para corregir)
npm run typecheck      # tsc en modo estricto
npm test               # Vitest + Testing Library (jsdom)
npm run build          # comprobación de tipos + build de producción en dist/ (sin source maps)
npm audit              # vulnerabilidades conocidas en las dependencias
```

## Configuración

Variables `VITE_*` en `web/.env` (ver la sección "Frontend" de `.env.example` en la raíz). **Todo
lo que lleva `VITE_` termina en el JavaScript público**: nunca secretos. `src/config.ts` las lee y
rechaza URLs que no sean `http(s)` o que lleven credenciales.

| Variable             | Para qué                                                             |
| -------------------- | -------------------------------------------------------------------- |
| `VITE_API_URL`       | Origen de la API; vacío = el mismo del frontend (detrás del proxy)   |
| `VITE_MAP_STYLE_URL` | Estilo de tiles de MapLibre; vacío = OpenFreeMap, sin key (ADR-0010) |

## Ver el mapa en local

Con la base, Redis, la API (`uvicorn app.main:app`), el simulador y el worker en marcha (ver
`AGENTS.md` §10), `npm run dev` y abrir `http://localhost:5173`. El proxy de Vite deja la API en
el mismo origen, así que `CORS_ORIGINS` solo necesita `http://localhost:5173`. Hace falta una
cuenta (`POST /api/v1/auth/register` o `/docs`).

## Cómo está organizado

| Carpeta        | Qué hay                                                                               |
| -------------- | ------------------------------------------------------------------------------------- |
| `src/auth/`    | Login; el access token vive solo en memoria (AGENTS.md §8.4)                          |
| `src/live/`    | Protocolo de `/ws/live`, estado de los buques y el hook `useLiveVessels`              |
| `src/api/`     | Cliente REST de `/api/v1` con el token en la cabecera (`ApiError` con el código HTTP) |
| `src/vessels/` | Ficha del buque (`VesselPanel`), estela de 30 min, consultas con TanStack Query       |
| `src/map/`     | `VesselMap` (MapLibre), GeoJSON, categorías y colores, iconos SDF y viewport          |

Al hacer clic en un buque se abre su ficha y se dibuja su estela (`GET /vessels/{mmsi}/history`,
recargada cada 15 s). La estela se corta donde faltan más de 5 minutos de señal, para no inventar
un trayecto. Escape o un clic en el mar cierran la ficha.

Sin reconexión ni renovación del token todavía (tarea 4.5): si la sesión caduca (cierre `4401`
del WebSocket o 401 de la API), vuelve a pedir el login.

## Seguridad

- Los datos de buques vienen de AIS y cualquiera puede escribirlos: se muestran **siempre como
  texto**. ESLint prohíbe `dangerouslySetInnerHTML`, asignar `innerHTML`/`outerHTML`,
  `insertAdjacentHTML` y `Popup.setHTML()` de MapLibre (AGENTS.md §8.7);
  `src/test/lint-rules.test.ts` comprueba que la regla sigue activa.
- Sin source maps en el build de producción (AGENTS.md §8.12).
