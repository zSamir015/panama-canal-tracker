import type { VesselSummary } from '../vessels/api';
import type { TrailWindowId } from '../vessels/trailWindow';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

export interface HistoryPeriod {
  id: string;
  label: string;
  /** Cuánto se mira hacia atrás. */
  ms: number;
  /** Ventana de estela con la que se abre el buque: la mayor que no pasa del periodo. */
  trail: TrailWindowId;
}

export const HISTORY_PERIODS: readonly HistoryPeriod[] = [
  { id: '24h', label: '24 horas', ms: DAY, trail: '24h' },
  { id: '48h', label: '48 horas', ms: 2 * DAY, trail: '48h' },
  { id: '7d', label: '7 días', ms: 7 * DAY, trail: '7d' },
  // La API guarda la estela de un buque hasta 7 días por consulta.
  { id: '30d', label: '30 días', ms: 30 * DAY, trail: '7d' },
];

/** Filas que se pintan a la vez: con cientos de buques, el filtro ayuda más que desplazarse. */
export const MAX_ROWS = 200;

/** «hace 5 min», «hace 3 h» o «hace 4 d»: a partir de 48 h se cuenta en días. */
export function seenText(iso: string | null, now: number): string {
  if (iso === null) {
    return '—';
  }
  const elapsed = now - Date.parse(iso);
  if (Number.isNaN(elapsed)) {
    return '—';
  }
  const minutes = Math.max(0, Math.round(elapsed / 60_000));
  if (minutes < 60) {
    return `hace ${String(minutes)} min`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `hace ${String(hours)} h`;
  }
  return `hace ${String(Math.round(hours / 24))} d`;
}

export function matchesFilter(vessel: VesselSummary, needle: string): boolean {
  if (needle === '') {
    return true;
  }
  return (
    (vessel.name ?? '').toLowerCase().includes(needle) ||
    String(vessel.mmsi).includes(needle) ||
    (vessel.imo !== null && String(vessel.imo).includes(needle))
  );
}
