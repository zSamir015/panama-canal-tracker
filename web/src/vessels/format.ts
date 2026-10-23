import { CATEGORY_LABELS, shipCategory } from '../map/vesselGeoJson';

/** Estado de navegación AIS (ITU-R M.1371, mensaje 1, campo "navigational status"). */
const NAV_STATUS: Readonly<Record<number, string>> = {
  0: 'Navegando con motor',
  1: 'Fondeado',
  2: 'Sin gobierno',
  3: 'Maniobrabilidad restringida',
  4: 'Restringido por su calado',
  5: 'Amarrado',
  6: 'Varado',
  7: 'Pescando',
  8: 'Navegando a vela',
};

const NO_DATA = '—';

export function shipTypeText(shipType: number | null): string {
  const label = CATEGORY_LABELS[shipCategory(shipType)];
  return shipType === null ? label : `${label} (${String(shipType)})`;
}

export function navStatusText(status: number | null): string {
  if (status === null) {
    return NO_DATA;
  }
  return NAV_STATUS[status] ?? `Sin definir (${String(status)})`;
}

export function speedText(sog: number | null): string {
  return sog === null ? NO_DATA : `${sog.toFixed(1)} nudos`;
}

export function courseText(cog: number | null): string {
  return cog === null ? NO_DATA : `${String(Math.round(cog))}°`;
}

export function dimensionsText(length: number | null, beam: number | null): string {
  if (length === null && beam === null) {
    return NO_DATA;
  }
  const meters = (value: number | null) =>
    value === null ? '?' : `${String(Math.round(value))} m`;
  return `${meters(length)} × ${meters(beam)}`;
}

/** "hace 3 min" a partir de una fecha ISO; el reloj se inyecta para poder probarlo. */
export function agoText(iso: string | null, now: number): string {
  if (iso === null) {
    return NO_DATA;
  }
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (Number.isNaN(seconds)) {
    return NO_DATA;
  }
  if (seconds < 60) {
    return `hace ${String(seconds)} s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `hace ${String(minutes)} min`;
  }
  return `hace ${String(Math.round(minutes / 60))} h`;
}
