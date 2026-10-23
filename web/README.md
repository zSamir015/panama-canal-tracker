# web/ — Mapa en tiempo real

Frontend del proyecto (Fase 4 del roadmap, ADR-0006): React + TypeScript (`strict`) + Vite.
Se conectará a la API por REST y a `/ws/live` para las posiciones en vivo; el mapa (MapLibre GL)
llega en la tarea 4.3.

## Requisitos

Node `^22.22.2`, `^24.15.0` o `>=26` (lo que admiten Vite, Vitest y jsdom; ver `engines` en
`package.json`).

## Comandos

```bash
cd web
npm ci                 # instala exactamente lo de package-lock.json
npm run dev            # servidor de desarrollo en http://localhost:5173
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

| Variable             | Para qué                                                                    |
| -------------------- | --------------------------------------------------------------------------- |
| `VITE_API_URL`       | Origen de la API; vacío = el mismo del frontend (detrás del proxy)          |
| `VITE_MAP_STYLE_URL` | Estilo de tiles de MapLibre (ADR-0006; el proveedor se decide en la Fase 4) |

## Seguridad

- Los datos de buques vienen de AIS y cualquiera puede escribirlos: se muestran **siempre como
  texto**. ESLint prohíbe `dangerouslySetInnerHTML`, asignar `innerHTML`/`outerHTML`,
  `insertAdjacentHTML` y `Popup.setHTML()` de MapLibre (AGENTS.md §8.7);
  `src/test/lint-rules.test.ts` comprueba que la regla sigue activa.
- Sin source maps en el build de producción (AGENTS.md §8.12).
