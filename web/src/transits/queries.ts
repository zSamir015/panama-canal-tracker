import { useQuery } from '@tanstack/react-query';
import { fetchCurrentTransits } from './api';

/** Cada cuánto se recarga la lista: un tránsito dura horas, no hace falta más a menudo. */
export const TRANSITS_REFRESH_MS = 30_000;

/** Sin sesión no pide nada. */
export function useCurrentTransits(token: string | null) {
  return useQuery({
    // El token va en la clave: un 401 se queda con el token caducado, no con el nuevo.
    queryKey: ['transits', 'current', token],
    queryFn: () => {
      if (token === null) {
        throw new Error('Sin sesión');
      }
      return fetchCurrentTransits(token);
    },
    enabled: token !== null,
    refetchInterval: TRANSITS_REFRESH_MS,
  });
}
