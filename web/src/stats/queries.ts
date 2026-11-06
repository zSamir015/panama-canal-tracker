import { useQuery } from '@tanstack/react-query';
import { fetchDailyStats, fetchTransitDurations, fetchWaitingTimes } from './api';

/** Cada cuánto se recargan las estadísticas: cambian con cada tránsito, que dura horas. */
export const STATS_REFRESH_MS = 5 * 60_000;

/** Ventanas que se pueden elegir, en días. */
export const WINDOW_OPTIONS = [7, 30, 90] as const;
export type WindowDays = (typeof WINDOW_OPTIONS)[number];

function options(token: string | null, days: number) {
  // El token va en la clave: un 401 se queda con el token caducado, no con el nuevo.
  return { enabled: token !== null, refetchInterval: STATS_REFRESH_MS, key: [days, token] };
}

function needToken(token: string | null): string {
  if (token === null) {
    throw new Error('Sin sesión');
  }
  return token;
}

export function useDailyStats(token: string | null, days: number) {
  const { key, ...rest } = options(token, days);
  return useQuery({
    queryKey: ['stats', 'daily', ...key],
    queryFn: () => fetchDailyStats(needToken(token), days),
    ...rest,
  });
}

export function useTransitDurations(token: string | null, days: number) {
  const { key, ...rest } = options(token, days);
  return useQuery({
    queryKey: ['stats', 'durations', ...key],
    queryFn: () => fetchTransitDurations(needToken(token), days),
    ...rest,
  });
}

export function useWaitingTimes(token: string | null, days: number) {
  const { key, ...rest } = options(token, days);
  return useQuery({
    queryKey: ['stats', 'waiting', ...key],
    queryFn: () => fetchWaitingTimes(needToken(token), days),
    ...rest,
  });
}
