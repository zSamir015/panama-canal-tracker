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

export function fetchVesselDetail(
  mmsi: number,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<VesselDetail> {
  return apiGet(`/vessels/${String(mmsi)}`, token, parseVesselDetail, fetchImpl);
}

/** La estela: por defecto, los últimos 30 minutos que decide el servidor. */
export function fetchVesselTrack(
  mmsi: number,
  token: string,
  fetchImpl?: typeof fetch,
): Promise<VesselTrack> {
  return apiGet(`/vessels/${String(mmsi)}/history`, token, parseVesselTrack, fetchImpl);
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
