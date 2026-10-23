import { config } from '../config';

export class LoginError extends Error {
  override name = 'LoginError';
}

/**
 * `POST /api/v1/auth/login`. Devuelve el access token, que se guarda solo en memoria (AGENTS.md
 * §8.4); el refresh token llega en una cookie `HttpOnly` que JavaScript no puede leer.
 */
export async function login(
  email: string,
  password: string,
  fetchImpl: typeof fetch = fetch,
): Promise<string> {
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

  const body: unknown = await response.json();
  if (
    typeof body !== 'object' ||
    body === null ||
    !('access_token' in body) ||
    typeof body.access_token !== 'string'
  ) {
    throw new LoginError('Respuesta inesperada de la API.');
  }
  return body.access_token;
}
