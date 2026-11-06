import { apiGet } from '../api/client';

export type TransitDirection = 'northbound' | 'southbound';

/** Un tránsito en curso de `GET /api/v1/transits/current` (docs/API_DESIGN.md). */
export interface CurrentTransit {
  id: string;
  mmsi: number;
  /** Texto AIS tal cual: se muestra como texto, nunca como HTML. */
  vessel_name: string | null;
  ship_type: number | null;
  direction: TransitDirection;
  entered_at: string;
}

export interface CurrentTransits {
  items: CurrentTransit[];
  /** Cuántos hay en total; puede superar `items.length` si la API recortó la lista. */
  total: number;
}

export function fetchCurrentTransits(
  token: string,
  fetchImpl?: typeof fetch,
): Promise<CurrentTransits> {
  return apiGet('/transits/current', token, parseCurrentTransits, fetchImpl);
}

export function parseCurrentTransits(body: unknown): CurrentTransits | null {
  if (!isRecord(body) || !Array.isArray(body.items) || !isCount(body.total)) {
    return null;
  }
  const items: CurrentTransit[] = [];
  for (const raw of body.items) {
    const item = parseTransit(raw);
    if (item === null) {
      return null;
    }
    items.push(item);
  }
  return { items, total: body.total };
}

function parseTransit(raw: unknown): CurrentTransit | null {
  if (
    !isRecord(raw) ||
    typeof raw.id !== 'string' ||
    !Number.isInteger(raw.mmsi) ||
    !isNullable(raw.vessel_name, isString) ||
    !isNullable(raw.ship_type, isNumber) ||
    (raw.direction !== 'northbound' && raw.direction !== 'southbound') ||
    typeof raw.entered_at !== 'string' ||
    Number.isNaN(Date.parse(raw.entered_at))
  ) {
    return null;
  }
  return {
    id: raw.id,
    mmsi: raw.mmsi as number,
    vessel_name: raw.vessel_name as string | null,
    ship_type: raw.ship_type as number | null,
    direction: raw.direction,
    entered_at: raw.entered_at,
  };
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullable(value: unknown, check: (value: unknown) => boolean): boolean {
  return value === null || check(value);
}
