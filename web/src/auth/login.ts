import { config } from '../config';
import { parseTokenResponse, type Session } from './session';

export class LoginError extends Error {
  override name = 'LoginError';
}

/**
 * `POST /api/v1/auth/login`. Devuelve la sesión (access token y caducidad), que se guarda solo en
 * memoria (AGENTS.md §8.4); el refresh token llega en una cookie `HttpOnly` que JavaScript no puede
 * leer.
 */
export async function login(
  email: string,
  password: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Session> {
  let response: Response;
  try {
    response = await fetchImpl(`${config.apiUrl}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new LoginError('No se pudo conectar con la API.');
  }

  if (response.status === 401) {
    throw new LoginError('Email o contraseña incorrectos.');
  }
  if (response.status === 429) {
    throw new LoginError('Demasiados intentos. Espera un minuto y vuelve a probar.');
  }
  if (!response.ok) {
    throw new LoginError('No se pudo iniciar sesión. Inténtalo de nuevo.');
  }

  const session = parseTokenResponse(await response.json());
  if (!session) {
    throw new LoginError('Respuesta inesperada de la API.');
  }
  return session;
}

/**
 * `POST /api/v1/auth/register` seguido de `login` automático. El rol no se envía nunca: el
 * servidor siempre asigna `user` (AGENTS.md §8.3).
 */
export async function register(
  email: string,
  password: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Session> {
  let response: Response;
  try {
    response = await fetchImpl(`${config.apiUrl}/api/v1/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new LoginError('No se pudo conectar con la API.');
  }

  if (response.status === 409) {
    throw new LoginError('Ese email ya está registrado.');
  }
  if (response.status === 422) {
    throw new LoginError('Revisa el email y la contraseña (mínimo 12 caracteres).');
  }
  if (response.status === 429) {
    throw new LoginError('Demasiados intentos. Espera un minuto y vuelve a probar.');
  }
  if (!response.ok) {
    throw new LoginError('No se pudo crear la cuenta. Inténtalo de nuevo.');
  }

  return login(email, password, fetchImpl);
}
