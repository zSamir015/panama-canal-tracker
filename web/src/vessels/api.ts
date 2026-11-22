import { apiGet } from '../api/client';

/** `GET /api/v1/vessels/{mmsi}` (docs/API_DESIGN.md). Los textos son AIS: se muestran como texto. */
export interface VesselDetail {
  mmsi: number;
  name: string | null;
  imo: number | null;
  ship_type: number | null;
  length_m: number | null;
  beam_m: number | null;
  last_seen_at: string | null;
  last_position: {
    received_at: string;
    lat: number;
    lon: number;
    sog: number | null;
    cog: number | null;
    heading: number | null;
    nav_status: number | null;
  } | null;
}

/** `GET /api/v1/vessels/{mmsi}/history`: posiciones en orden cronológico. */
export interface VesselTrack {
  coordinates: [number, number][];
  timestamps: string[];
  truncated: boolean;
}

export interface VesselSummary {
  mmsi: number;
  name: string | null;
  imo: number | null;
  ship_type: number | null;
  last_seen_at: string | null;
  lat: number | null;
  lon: number | null;
}

/** Tamaño máximo de página de `GET /vessels` y tope de páginas (2 000 buques). */
export const DIRECTORY_PAGE_SIZE = 200;
export const DIRECTORY_MAX_PAGES = 10;

/**
 * Todos los buques conocidos, página a página (los más vistos primero). Una sola página dejaba
 * fuera a los buques más antiguos del buscador en cuanto había más de 200.
 */
export async function fetchVesselDirectory(
  token: string,
  fetchImpl?: typeof fetch,
): Promise<VesselSummary[]> {
  const all: VesselSummary[] = [];
  for (let page = 1; page <= DIRECTORY_MAX_PAGES; page += 1) {
    const result = await apiGet(
      `/vessels?size=${String(DIRECTORY_PAGE_SIZE)}&page=${String(page)}`,
      token,
      parseVesselPage,
      fetchImpl,
    );
    all.push(...result.items);
    if (result.items.length === 0 || all.length >= result.total) {
      break;
    }
  }
  return all;
}

function parseVesselPage(body: unknown): { items: VesselSummary[]; total: number } | null {
  const items = parseVesselDirectory(body);
  if (items === null || !isRecord(body) || !Number.isInteger(body.total)) {
    return null;
  }
  return { items, total: body.total as number };
}

export function fetchVesselDetail(
  mmsi: number,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<VesselDetail> {
  return apiGet(`/vessels/${String(mmsi)}`, token, parseVesselDetail, fetchImpl);
}

/**
 * La estela. Sin `windowMs`, los últimos 30 minutos que decide el servidor; con él, desde hace
 * esa cantidad de milisegundos hasta ahora (`from` es una hora con zona, en UTC).
 */
export function fetchVesselTrack(
  mmsi: number,
  token: string,
  fetchImpl?: typeof fetch,
  windowMs?: number,
): Promise<VesselTrack> {
  const query =
    windowMs === undefined
      ? ''
      : `?from=${encodeURIComponent(new Date(Date.now() - windowMs).toISOString())}`;
  return apiGet(`/vessels/${String(mmsi)}/history${query}`, token, parseVesselTrack, fetchImpl);
}

export function parseVesselDirectory(body: unknown): VesselSummary[] | null {
  if (!isRecord(body) || !Array.isArray(body.items)) {
    return null;
  }
  const items: VesselSummary[] = [];
  for (const raw of body.items) {
    if (
      !isRecord(raw) ||
      !Number.isInteger(raw.mmsi) ||
      !isNullable(raw.name, isString) ||
      !isNullable(raw.imo, isNumber) ||
      !isNullable(raw.ship_type, isNumber) ||
      !isNullable(raw.last_seen_at, isString)
    ) {
      return null;
    }
    items.push({
      mmsi: raw.mmsi as number,
      name: (raw.name as string | null) ?? null,
      imo: (raw.imo as number | null) ?? null,
      ship_type: (raw.ship_type as number | null) ?? null,
      last_seen_at: (raw.last_seen_at as string | null) ?? null,
      lat: null,
      lon: null,
    });
  }
  return items;
}

export function parseVesselDetail(body: unknown): VesselDetail | null {
  if (
    !isRecord(body) ||
    !Number.isInteger(body.mmsi) ||
    !isNullable(body.name, isString) ||
    !isNullable(body.imo, isNumber) ||
    !isNullable(body.ship_type, isNumber) ||
    !isNullable(body.length_m, isNumber) ||
    !isNullable(body.beam_m, isNumber) ||
    !isNullable(body.last_seen_at, isString) ||
    !isNullable(body.last_position, isPosition)
  ) {
    return null;
  }
  return body as unknown as VesselDetail;
}

export function parseVesselTrack(body: unknown): VesselTrack | null {
  if (!isRecord(body) || !isRecord(body.properties)) {
    return null;
  }
  const { timestamps, truncated } = body.properties;
  if (!Array.isArray(timestamps) || !timestamps.every(isString) || typeof truncated !== 'boolean') {
    return null;
  }
  if (body.geometry === null) {
    return { coordinates: [], timestamps, truncated };
  }
  if (
    !isRecord(body.geometry) ||
    body.geometry.type !== 'LineString' ||
    !Array.isArray(body.geometry.coordinates) ||
    !body.geometry.coordinates.every(isLonLat)
  ) {
    return null;
  }
  return { coordinates: body.geometry.coordinates, timestamps, truncated };
}

function isPosition(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.received_at) &&
    isNumber(value.lat) &&
    isNumber(value.lon) &&
    isNullable(value.sog, isNumber) &&
    isNullable(value.cog, isNumber) &&
    isNullable(value.heading, isNumber) &&
    isNullable(value.nav_status, isNumber)
  );
}

function isLonLat(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every(isNumber);
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
