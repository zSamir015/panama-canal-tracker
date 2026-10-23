import { useQuery } from '@tanstack/react-query';
import { fetchVesselDetail, fetchVesselTrack } from './api';

/** Cada cuánto se recarga la estela mientras la ficha está abierta. */
export const TRACK_REFRESH_MS = 15_000;

export function useVesselDetail(mmsi: number, token: string) {
  return useQuery({
    // El token va en la clave: un error 401 se queda con el token caducado, no con el nuevo.
    queryKey: ['vessel', mmsi, token],
    queryFn: () => fetchVesselDetail(mmsi, token),
    // Los datos estáticos (nombre, dimensiones) casi no cambian; la posición llega por /ws/live.
    staleTime: 60_000,
  });
}

/** Sin buque seleccionado (o sin sesión) no pide nada. */
export function useVesselTrack(mmsi: number | null, token: string | null) {
  return useQuery({
    queryKey: ['vessel', mmsi, 'track', token],
    queryFn: () => {
      if (mmsi === null || token === null) {
        throw new Error('Sin buque o sin sesión');
      }
      return fetchVesselTrack(mmsi, token);
    },
    enabled: mmsi !== null && token !== null,
    refetchInterval: TRACK_REFRESH_MS,
  });
}
