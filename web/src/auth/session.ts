import { config } from '../config';

/** Access token en memoria y cuándo caduca (ms desde epoch, reloj del navegador). */
export interface Session {
  accessToken: string;
  expiresAt: number;
}

/** La renovación no se pudo hacer ahora (red, 429, 5xx): la sesión puede seguir valiendo. */
export class SessionError extends Error {
  override name = 'SessionError';
}

/**
 * Respuesta de `/auth/login` y `/auth/refresh` (`TokenResponse`). `expires_in` llega en segundos;
 * si faltara, se asume la duración por defecto del backend (15 min).
 */
export function parseTokenResponse(body: unknown, now: number = Date.now()): Session | null {
  if (typeof body !== 'object' || body === null) {
    return null;
  }
  const { access_token: accessToken, expires_in: expiresIn } = body as Record<string, unknown>;
  if (typeof accessToken !== 'string' || accessToken === '') {
    return null;
  }
  const seconds =
    typeof expiresIn === 'number' && Number.isFinite(expiresIn) && expiresIn > 0 ? expiresIn : 900;
  return { accessToken, expiresAt: now + seconds * 1000 };
}

/** Nombre del Web Lock que serializa las renovaciones entre pestañas del mismo origen. */
const REFRESH_LOCK = 'pct-auth-refresh';

let inFlight: Promise<Session | null> | null = null;

/**
 * `POST /api/v1/auth/refresh` con la cookie `HttpOnly`. Devuelve la sesión nueva, `null` si no hay
 * sesión que renovar (401) o lanza `SessionError` si ahora no se puede.
 *
 * Cada refresh rota la cookie y reutilizar una ya rotada revoca la sesión entera (AGENTS.md §8.4),
 * así que nunca hay dos renovaciones a la vez: las llamadas en paralelo de esta pestaña comparten
 * la misma petición y, entre pestañas, un Web Lock las pone en fila.
 */
export function refreshSession(fetchImpl: typeof fetch = fetch): Promise<Session | null> {
  inFlight ??= withRefreshLock(() => requestRefresh(fetchImpl)).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  // Sin Web Locks (navegadores antiguos, jsdom) queda la deduplicación dentro de la pestaña.
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
  return locks ? locks.request(REFRESH_LOCK, task) : task();
}

async function requestRefresh(fetchImpl: typeof fetch): Promise<Session | null> {
  let response: Response;
  try {
    response = await fetchImpl(`${config.apiUrl}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
  } catch {
    throw new SessionError('No se pudo conectar con la API.');
  }
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new SessionError(`La renovación respondió ${String(response.status)}.`);
  }
  const session = parseTokenResponse(await response.json());
  if (!session) {
    throw new SessionError('Respuesta inesperada de la API.');
  }
  return session;
}
