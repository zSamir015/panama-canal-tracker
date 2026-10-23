import type { Bbox } from '../live/protocol';

/** Zona del Canal (AGENTS.md §1): vista inicial del mapa. */
export const CANAL_BBOX: Bbox = [-80.2, 8.4, -79.2, 9.7];

/**
 * Convierte los límites visibles del mapa en el `bbox` de `/ws/live`, que exige
 * `-180 ≤ min_lon < max_lon ≤ 180` y no admite cruzar el antimeridiano: si la vista lo cruza o da
 * la vuelta al mundo, se pide toda la franja de longitudes.
 */
export function boundsToBbox(west: number, south: number, east: number, north: number): Bbox {
  const minLat = clamp(south, -90, 90);
  const maxLat = clamp(north, -90, 90);
  if (east - west >= 360 || west < -180 || east > 180) {
    return [-180, minLat, 180, maxLat];
  }
  return [round(west), round(minLat), round(east), round(maxLat)];
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

// Seis decimales (~10 cm) bastan y mantienen el mensaje corto.
function round(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}
