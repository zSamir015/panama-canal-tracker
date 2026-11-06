import { apiGet } from '../api/client';

export type Direction = 'northbound' | 'southbound';
export type AnchorageName = 'atlantic' | 'pacific';

/** Un día, sentido y categoría con tránsitos, de `GET /api/v1/stats/daily` (docs/API_DESIGN.md). */
export interface DailyItem {
  date: string;
  direction: Direction;
  ship_category: string;
  transits: number;
}

export interface DailyStats {
  items: DailyItem[];
}

/** Resumen de una muestra en minutos. Con `count` 0 los demás valores son `null`. */
export interface Distribution {
  count: number;
  mean_minutes: number | null;
  p50_minutes: number | null;
  p90_minutes: number | null;
}

export interface TransitDurations {
  overall: Distribution;
  by_direction: Record<Direction, Distribution>;
}

export interface WaitingTimes {
  overall: Distribution;
  by_anchorage: Record<AnchorageName, Distribution>;
}

/** `from` y `to` de la API: los últimos `days` días hasta `now` (el reloj se inyecta). */
export function windowParams(days: number, now: number): string {
  const params = new URLSearchParams({
    from: new Date(now - days * 86_400_000).toISOString(),
    to: new Date(now).toISOString(),
  });
  return params.toString();
}

export function fetchDailyStats(
  token: string,
  days: number,
  now: number = Date.now(),
  fetchImpl?: typeof fetch,
): Promise<DailyStats> {
  return apiGet(`/stats/daily?${windowParams(days, now)}`, token, parseDailyStats, fetchImpl);
}

export function fetchTransitDurations(
  token: string,
  days: number,
  now: number = Date.now(),
  fetchImpl?: typeof fetch,
): Promise<TransitDurations> {
  return apiGet(
    `/stats/transit-durations?${windowParams(days, now)}`,
    token,
    parseTransitDurations,
    fetchImpl,
  );
}

export function fetchWaitingTimes(
  token: string,
  days: number,
  now: number = Date.now(),
  fetchImpl?: typeof fetch,
): Promise<WaitingTimes> {
  return apiGet(
    `/stats/waiting-times?${windowParams(days, now)}`,
    token,
    parseWaitingTimes,
    fetchImpl,
  );
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseDailyStats(body: unknown): DailyStats | null {
  if (!isRecord(body) || !Array.isArray(body.items)) {
    return null;
  }
  const items: DailyItem[] = [];
  for (const raw of body.items) {
    if (
      !isRecord(raw) ||
      typeof raw.date !== 'string' ||
      !DATE.test(raw.date) ||
      (raw.direction !== 'northbound' && raw.direction !== 'southbound') ||
      typeof raw.ship_category !== 'string' ||
      !isCount(raw.transits)
    ) {
      return null;
    }
    items.push({
      date: raw.date,
      direction: raw.direction,
      ship_category: raw.ship_category,
      transits: raw.transits,
    });
  }
  return { items };
}

export function parseTransitDurations(body: unknown): TransitDurations | null {
  if (!isRecord(body) || !isRecord(body.by_direction)) {
    return null;
  }
  const overall = parseDistribution(body.overall);
  const northbound = parseDistribution(body.by_direction.northbound);
  const southbound = parseDistribution(body.by_direction.southbound);
  if (overall === null || northbound === null || southbound === null) {
    return null;
  }
  return { overall, by_direction: { northbound, southbound } };
}

export function parseWaitingTimes(body: unknown): WaitingTimes | null {
  if (!isRecord(body) || !isRecord(body.by_anchorage)) {
    return null;
  }
  const overall = parseDistribution(body.overall);
  const atlantic = parseDistribution(body.by_anchorage.atlantic);
  const pacific = parseDistribution(body.by_anchorage.pacific);
  if (overall === null || atlantic === null || pacific === null) {
    return null;
  }
  return { overall, by_anchorage: { atlantic, pacific } };
}

function parseDistribution(raw: unknown): Distribution | null {
  if (
    !isRecord(raw) ||
    !isCount(raw.count) ||
    !isNullableNumber(raw.mean_minutes) ||
    !isNullableNumber(raw.p50_minutes) ||
    !isNullableNumber(raw.p90_minutes)
  ) {
    return null;
  }
  return {
    count: raw.count,
    mean_minutes: raw.mean_minutes,
    p50_minutes: raw.p50_minutes,
    p90_minutes: raw.p90_minutes,
  };
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
