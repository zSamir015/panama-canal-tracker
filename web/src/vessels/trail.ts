import type { Feature, MultiLineString, Position } from 'geojson';
import type { LiveVessel } from '../live/protocol';
import type { VesselTrack } from './api';

/**
 * Sin señal durante más de esto, la estela se corta: unir los dos extremos con una recta
 * inventaría un trayecto que nadie ha visto (el buque salió de cobertura o el receptor cayó).
 */
export const TRAIL_GAP_MS = 5 * 60_000;

/**
 * Estela del buque: la trayectoria de la API más la posición en vivo si es más reciente, para que
 * la línea llegue hasta la flecha. Un tramo por cada racha de señal sin huecos largos; `null` si
 * ningún tramo tiene dos puntos.
 */
export function trailFeature(
  track: VesselTrack | undefined,
  live: LiveVessel | undefined,
): Feature<MultiLineString> | null {
  const points: { position: Position; time: number }[] = (track?.coordinates ?? []).map(
    (position, index) => ({ position, time: Date.parse(track?.timestamps[index] ?? '') }),
  );
  const liveTime = live ? Date.parse(live.ts) : NaN;
  const lastTime = points.at(-1)?.time;
  if (live && (lastTime === undefined || liveTime > lastTime)) {
    points.push({ position: [live.lon, live.lat], time: liveTime });
  }

  const segments: Position[][] = [];
  let previous: number | undefined;
  for (const { position, time } of points) {
    const current = segments.at(-1);
    // Sin hora válida no se puede medir el hueco: se sigue el tramo actual.
    if (current && (previous === undefined || !(time - previous > TRAIL_GAP_MS))) {
      current.push(position);
    } else {
      segments.push([position]);
    }
    previous = Number.isNaN(time) ? previous : time;
  }

  const lines = segments.filter((segment) => segment.length >= 2);
  if (lines.length === 0) {
    return null;
  }
  return {
    type: 'Feature',
    geometry: { type: 'MultiLineString', coordinates: lines },
    properties: {},
  };
}
