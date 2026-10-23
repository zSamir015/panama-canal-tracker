import { config } from '../config';

/** Error de la API con su código HTTP (0 si ni siquiera hubo respuesta). */
export class ApiError extends Error {
  override name = 'ApiError';

  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * `GET` autenticado a `/api/v1`. `parse` comprueba la forma de la respuesta: lo que no encaje es
 * un error, no datos a medias.
 */
export async function apiGet<T>(
  path: string,
  token: string,
  parse: (body: unknown) => T | null,
  fetchImpl: typeof fetch = fetch,
): Promise<T> {
  let response: Response;
  try {
    response = await fetchImpl(`${config.apiUrl}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError(0, 'No se pudo conectar con la API.');
  }
  if (!response.ok) {
    throw new ApiError(response.status, messageFor(response.status));
  }
  const parsed = parse(await response.json());
  if (parsed === null) {
    throw new ApiError(response.status, 'Respuesta inesperada de la API.');
  }
  return parsed;
}

function messageFor(status: number): string {
  switch (status) {
    case 401:
      return 'La sesión caducó.';
    case 404:
      return 'No hay datos de este buque.';
    case 429:
      return 'Demasiadas peticiones. Espera un momento.';
    default:
      return 'La API no respondió bien. Inténtalo de nuevo.';
  }
}
