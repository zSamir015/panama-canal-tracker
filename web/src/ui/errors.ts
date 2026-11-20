import { ApiError } from '../api/client';

/**
 * Convierte cualquier fallo en un mensaje claro en español para no enseñar errores técnicos ni
 * trazas de red al usuario.
 */
export function friendlyError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return fallback;
}
