/**
 * Iconos de los buques generados en código (sin sprites externos):
 * - Casco y fondeo en SDF monocromo para que MapLibre los tiña por categoría (`icon-color`) con
 *   halo adaptable al fondo claro/oscuro/satélite.
 * - Superestructura de puente en RGBA @2x para dar lectura inmediata de buque real vista desde
 *   arriba, orientada con el rumbo (`cog`).
 */

export interface IconImage {
  width: number;
  height: number;
  data: Uint8Array;
}

export type SdfImage = IconImage;

type Point = readonly [number, number];

export const ICON_SIZE = 32;
export const CABIN_SCALE = 2;
export const CABIN_SIZE = ICON_SIZE * CABIN_SCALE;

// Parámetros estándar de MapLibre (`@mapbox/tiny-sdf`): borde en alfa 0.75 y caída 1/8 por px.
const SDF_CUTOFF = 0.25;
const SDF_RADIUS = 8;

/** Silueta naval vista desde arriba (proa afilada al norte, manga paralela y popa estrechada). */
const SHIP_HULL: readonly Point[] = [
  [16, 2.4],
  [18.8, 6.4],
  [21.5, 10.6],
  [22, 14],
  [22, 24.8],
  [20.4, 28.4],
  [18.4, 29.2],
  [13.6, 29.2],
  [11.6, 28.4],
  [10, 24.8],
  [10, 14],
  [10.5, 10.6],
  [13.2, 6.4],
];

export function arrowIcon(): IconImage {
  return sdfImage((x, y) => polygonDistance([x, y], SHIP_HULL));
}

/** Baliza concéntrica para buques fondeados o sin rumbo válido. */
export function dotIcon(): IconImage {
  const center = ICON_SIZE / 2;
  return sdfImage((x, y) => {
    const radius = Math.hypot(x - center, y - center);
    const core = radius - 3.4;
    const ring = Math.abs(radius - 7.8) - 1.35;
    return Math.min(core, ring);
  });
}

/**
 * Puente de mando blanco y línea de cubierta (@2x) que se superponen al casco en movimiento.
 */
export function cabinIcon(): IconImage {
  const data = new Uint8Array(CABIN_SIZE * CABIN_SIZE * 4);
  const paintRect = (x0: number, y0: number, x1: number, y1: number, alpha: number) => {
    const startX = Math.max(0, Math.round(x0 * CABIN_SCALE));
    const endX = Math.min(CABIN_SIZE, Math.round(x1 * CABIN_SCALE));
    const startY = Math.max(0, Math.round(y0 * CABIN_SCALE));
    const endY = Math.min(CABIN_SIZE, Math.round(y1 * CABIN_SCALE));
    for (let py = startY; py < endY; py++) {
      for (let px = startX; px < endX; px++) {
        const offset = (py * CABIN_SIZE + px) * 4;
        data[offset] = 255;
        data[offset + 1] = 255;
        data[offset + 2] = 255;
        data[offset + 3] = Math.max(data[offset + 3] ?? 0, alpha);
      }
    }
  };

  // Línea sutil de escotillas/crujía en proa y centro.
  paintRect(15.2, 9.0, 16.8, 19.6, 115);
  // Caseta del puente cerca de popa con alerones estrechos.
  paintRect(12.2, 20.6, 19.8, 25.0, 235);
  paintRect(11.1, 21.8, 20.9, 23.4, 235);

  return { width: CABIN_SIZE, height: CABIN_SIZE, data };
}

/** `distance` devuelve la distancia firmada al borde: negativa dentro de la figura. */
function sdfImage(distance: (x: number, y: number) => number): IconImage {
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
