/**
 * Mensajes de `/ws/live` (docs/API_DESIGN.md). El servidor es nuestro, pero lo que llega por la
 * red se comprueba igual: un mensaje con otra forma se descarta en vez de romper el mapa.
 */

/** Una posición tal como la envía el servidor (`LiveVessel` en `app/schemas/live.py`). */
export interface LiveVessel {
  mmsi: number;
  lon: number;
  lat: number;
  cog: number | null;
  sog: number | null;
  ship_type: number | null;
  /** Texto libre de AIS: se muestra siempre como texto (AGENTS.md §8.7). */
  name: string | null;
  ts: string;
}

export type ServerMessage =
  | { type: 'snapshot'; vessels: LiveVessel[] }
  | { type: 'update'; vessels: LiveVessel[] }
  | { type: 'remove'; mmsi: number[] };

/** `[min_lon, min_lat, max_lon, max_lat]`, en orden GeoJSON. */
export type Bbox = readonly [number, number, number, number];

export function authMessage(token: string): string {
  return JSON.stringify({ type: 'auth', token });
}

export function subscribeMessage(bbox: Bbox): string {
  return JSON.stringify({ type: 'subscribe', bbox });
}

/** Devuelve el mensaje si tiene la forma esperada; si no, `null`. */
export function parseServerMessage(raw: unknown): ServerMessage | null {
  if (typeof raw !== 'string') {
    return null;
  }
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data)) {
    return null;
  }
  switch (data.type) {
    case 'snapshot':
    case 'update':
      return Array.isArray(data.vessels)
        ? { type: data.type, vessels: data.vessels.filter(isLiveVessel) }
        : null;
    case 'remove':
      return Array.isArray(data.mmsi)
        ? { type: 'remove', mmsi: (data.mmsi as unknown[]).filter(isInteger) }
        : null;
    default:
      return null;
  }
}

function isLiveVessel(value: unknown): value is LiveVessel {
  return (
    isRecord(value) &&
    Number.isInteger(value.mmsi) &&
    isFiniteNumber(value.lon) &&
    isFiniteNumber(value.lat) &&
    isNullableNumber(value.cog) &&
    isNullableNumber(value.sog) &&
    isNullableNumber(value.ship_type) &&
    (value.name === null || typeof value.name === 'string') &&
    typeof value.ts === 'string'
  );
}

function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}
