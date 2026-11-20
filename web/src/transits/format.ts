import type { TransitDirection } from './api';

const NO_DATA = '—';

const DIRECTION_TEXT: Readonly<Record<TransitDirection, string>> = {
  southbound: 'Atlántico → Pacífico',
  northbound: 'Pacífico → Atlántico',
};

export function directionText(direction: TransitDirection): string {
  return DIRECTION_TEXT[direction];
}

/** "lleva 2 h 15 min" desde la entrada al Canal; el reloj se inyecta para poder probarlo. */
export function elapsedText(enteredAt: string, now: number): string {
  const minutes = Math.floor(Math.max(0, now - Date.parse(enteredAt)) / 60_000);
  if (Number.isNaN(minutes)) {
    return NO_DATA;
  }
  if (minutes < 1) {
    return 'acaba de entrar';
  }
  if (minutes < 60) {
    return `lleva ${String(minutes)} min`;
  }
  const rest = minutes % 60;
  const hours = String(Math.floor(minutes / 60));
  return rest === 0 ? `lleva ${hours} h` : `lleva ${hours} h ${String(rest)} min`;
}

export interface TransitProgress {
  percent: number;
  label: string;
}

const DEFAULT_MEDIAN_TRANSIT_MINUTES = 540;

/**
 * Estima el avance porcentual del tránsito y el tiempo restante a partir de la duración mediana
 * reciente (o ~9 h si aún no hay suficientes tránsitos históricos).
 */
export function transitProgress(
  enteredAt: string,
  now: number,
  medianMinutes: number | null | undefined,
): TransitProgress | null {
  const baseline =
    medianMinutes !== null && medianMinutes !== undefined && medianMinutes > 0
      ? medianMinutes
      : DEFAULT_MEDIAN_TRANSIT_MINUTES;
  const elapsedMin = (now - Date.parse(enteredAt)) / 60_000;
  if (Number.isNaN(elapsedMin)) {
    return null;
  }
  const safeElapsed = Math.max(0, elapsedMin);
  const percent = Math.min(98, Math.max(2, Math.round((safeElapsed / baseline) * 100)));
  const remainingMin = Math.round(baseline - safeElapsed);
  if (remainingMin <= 15) {
    return { percent, label: `≈ ${String(percent)} %, por salir` };
  }
  if (remainingMin < 60) {
    return {
      percent,
      label: `≈ ${String(percent)} %, sale en ~${String(remainingMin)} min`,
    };
  }
  const hours = Math.max(1, Math.round(remainingMin / 60));
  const unit = hours === 1 ? 'una 1 h' : `unas ${String(hours)} h`;
  return { percent, label: `≈ ${String(percent)} %, sale en ${unit}` };
}

export function transitName(name: string | null, mmsi: number): string {
  const trimmed = name?.trim();
  // AIS rellena con espacios: un nombre en blanco es lo mismo que no tenerlo.
  return trimmed === undefined || trimmed === '' ? `MMSI ${String(mmsi)}` : trimmed;
}
