/**
 * Content-Security-Policy del frontend (AGENTS.md §8.11), construida con la misma configuración
 * que lee la aplicación: la API (`VITE_API_URL`, vacío = el mismo origen) y el proveedor de tiles
 * (`VITE_MAP_STYLE_URL`, ADR-0010). Así cambiar de API o de tiles no deja la política vieja.
 *
 * No importa `src/config.ts`: ese módulo lee `import.meta.env` al cargarse y no funciona en Node,
 * donde corre la configuración de Vite. `csp.test.ts` comprueba que el origen de tiles por defecto
 * es el mismo que usa la aplicación.
 *
 * Los scripts solo pueden venir del propio origen: sin `unsafe-inline` ni `unsafe-eval`. Los
 * estilos sí llevan `unsafe-inline`, porque MapLibre escribe estilos en línea, y los workers pueden
 * venir del propio origen (MapLibre 6 sirve el suyo como fichero) o de `blob:`. Un `<meta>` ignora
 * `frame-ancestors`: con un proxy propio hay que mandarlo como cabecera.
 */
/** OpenFreeMap (ADR-0010): el origen de los tiles si no se configura otro. */
export const DEFAULT_TILES_ORIGIN = 'https://tiles.openfreemap.org';

/** El origen de una URL de la configuración; falla si no es http(s), como `readConfig`. */
function origin(value: string | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) {
    return null;
  }
  const url = new URL(trimmed);
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error(`URL no admitida en la configuración: ${url.protocol}`);
  }
  return url.origin;
}

export function buildCsp(env: Record<string, string | undefined>): string {
  const tiles = origin(env.VITE_MAP_STYLE_URL) ?? DEFAULT_TILES_ORIGIN;
  const connect = ["'self'", tiles];
  const apiOrigin = origin(env.VITE_API_URL);
  if (apiOrigin !== null) {
    const api = new URL(apiOrigin);
    // El WebSocket de `/ws/live` va al mismo host que la API, con ws:// o wss://.
    const socket = `${api.protocol === 'https:' ? 'wss' : 'ws'}://${api.host}`;
    connect.push(apiOrigin, socket);
  }
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${tiles}`,
    `font-src 'self' ${tiles}`,
    `connect-src ${connect.join(' ')}`,
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ');
}
