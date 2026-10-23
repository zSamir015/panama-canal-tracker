/**
 * Iconos de los buques generados en código como SDF (signed distance field): una sola imagen
 * monocroma que MapLibre colorea con `icon-color`, así no hace falta una imagen por categoría ni
 * descargar sprites de otro origen.
 */

export interface SdfImage {
  width: number;
  height: number;
  data: Uint8Array;
}

type Point = readonly [number, number];

export const ICON_SIZE = 32;

// Los mismos parámetros que usa MapLibre al generar sus SDF (`@mapbox/tiny-sdf`): el borde de la
// figura queda en alfa 0.75 y cada píxel de distancia resta 1/8.
const SDF_CUTOFF = 0.25;
const SDF_RADIUS = 8;

/** Flecha que apunta al norte; `icon-rotate` la gira según el rumbo. */
const ARROW: readonly Point[] = [
  [16, 3],
  [26, 28],
  [16, 22],
  [6, 28],
];

export function arrowIcon(): SdfImage {
  return sdfImage((x, y) => polygonDistance([x, y], ARROW));
}

/** Punto para los buques sin rumbo (fondeados o sin dato). */
export function dotIcon(): SdfImage {
  const center = ICON_SIZE / 2;
  return sdfImage((x, y) => Math.hypot(x - center, y - center) - 6);
}

/** `distance` devuelve la distancia firmada al borde: negativa dentro de la figura. */
function sdfImage(distance: (x: number, y: number) => number): SdfImage {
  const data = new Uint8Array(ICON_SIZE * ICON_SIZE * 4);
  for (let y = 0; y < ICON_SIZE; y++) {
    for (let x = 0; x < ICON_SIZE; x++) {
      // Centro del píxel.
      const d = distance(x + 0.5, y + 0.5);
      const alpha = Math.round(255 * Math.min(1, Math.max(0, 1 - SDF_CUTOFF - d / SDF_RADIUS)));
      const offset = (y * ICON_SIZE + x) * 4;
      data[offset + 3] = alpha;
    }
  }
  return { width: ICON_SIZE, height: ICON_SIZE, data };
}

function polygonDistance(point: Point, polygon: readonly Point[]): number {
  let min = Infinity;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i];
    const b = polygon[j];
    if (!a || !b) {
      continue;
    }
    min = Math.min(min, segmentDistance(point, a, b));
    // Regla par-impar: cuántos lados cruza un rayo horizontal hacia la derecha.
    if (a[1] > point[1] !== b[1] > point[1]) {
      const crossX = a[0] + ((point[1] - a[1]) / (b[1] - a[1])) * (b[0] - a[0]);
      if (point[0] < crossX) {
        inside = !inside;
      }
    }
  }
  return inside ? -min : min;
}

function segmentDistance(p: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const t = Math.max(
    0,
    Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)),
  );
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}
