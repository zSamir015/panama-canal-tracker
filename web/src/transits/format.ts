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

export function transitName(name: string | null, mmsi: number): string {
  const trimmed = name?.trim();
  // AIS rellena con espacios: un nombre en blanco es lo mismo que no tenerlo.
  return trimmed === undefined || trimmed === '' ? `MMSI ${String(mmsi)}` : trimmed;
}
