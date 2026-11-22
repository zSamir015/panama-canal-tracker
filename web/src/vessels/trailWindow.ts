/**
 * Ventanas de la estela de la ficha. La API admite hasta 7 días (`MAX_TRACK_DAYS`) y como mucho
 * 2000 puntos: si hay más, devuelve los más recientes y avisa con `truncated`.
 */
export type TrailWindowId = '30m' | '6h' | '24h' | '7d';

export interface TrailWindow {
  id: TrailWindowId;
  label: string;
  /** Texto para «Estela: últimos …». */
  phrase: string;
  /** Cuánto se mira hacia atrás. */
  ms: number;
  /**
   * Hueco de señal a partir del cual la estela se corta. Crece con la ventana porque la cobertura
   * AIS gratuita es escasa: en 7 días lo normal es tener una posición cada pocos minutos o horas.
   */
  gapMs: number;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/** La que decide el servidor cuando no se pide otra (`DEFAULT_TRACK_MINUTES`). */
export const DEFAULT_TRAIL_WINDOW: TrailWindow = {
  id: '30m',
  label: '30 min',
  phrase: '30 minutos',
  ms: 30 * MINUTE,
  gapMs: 5 * MINUTE,
};

export const TRAIL_WINDOWS: readonly TrailWindow[] = [
  DEFAULT_TRAIL_WINDOW,
  { id: '6h', label: '6 h', phrase: '6 horas', ms: 6 * HOUR, gapMs: 30 * MINUTE },
  { id: '24h', label: '24 h', phrase: '24 horas', ms: 24 * HOUR, gapMs: 2 * HOUR },
  // 5 min menos de 7 días: el servidor rechaza una ventana mayor y su reloj va por delante.
  { id: '7d', label: '7 días', phrase: '7 días', ms: 7 * 24 * HOUR - 5 * MINUTE, gapMs: 6 * HOUR },
];

export function trailWindow(id: TrailWindowId): TrailWindow {
  return TRAIL_WINDOWS.find((item) => item.id === id) ?? DEFAULT_TRAIL_WINDOW;
}
