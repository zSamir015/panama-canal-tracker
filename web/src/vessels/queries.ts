import { useQuery } from '@tanstack/react-query';
import { fetchVesselDetail, fetchVesselDirectory, fetchVesselTrack } from './api';
import { DEFAULT_TRAIL_WINDOW, type TrailWindowId, trailWindow } from './trailWindow';

/** Cada cuánto se recarga la estela mientras la ficha está abierta. */
export const TRACK_REFRESH_MS = 15_000;
/** Las ventanas largas pesan más (hasta 2 000 puntos) y cambian poco: se recargan más despacio. */
export const LONG_TRACK_REFRESH_MS = 60_000;

export function useVesselDirectory(token: string | null) {
  return useQuery({
    queryKey: ['vessels', 'directory', token],
    queryFn: () => {
      if (token === null) {
        throw new Error('Sin sesión');
      }
      return fetchVesselDirectory(token);
    },
    enabled: token !== null,
    staleTime: 60_000,
  });
}

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
export function useVesselTrack(
  mmsi: number | null,
  token: string | null,
  windowId: TrailWindowId = DEFAULT_TRAIL_WINDOW.id,
) {
  const selected = trailWindow(windowId);
  const isDefault = selected.id === DEFAULT_TRAIL_WINDOW.id;
  return useQuery({
    queryKey: ['vessel', mmsi, 'track', windowId, token],
    queryFn: () => {
      if (mmsi === null || token === null) {
        throw new Error('Sin buque o sin sesión');
      }
      // La ventana por defecto la decide el servidor; las demás se piden con `from`.
      return fetchVesselTrack(mmsi, token, undefined, isDefault ? undefined : selected.ms);
    },
    enabled: mmsi !== null && token !== null,
    refetchInterval: isDefault ? TRACK_REFRESH_MS : LONG_TRACK_REFRESH_MS,
  });
}
