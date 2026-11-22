export type AppView = 'map' | 'stats' | 'history';

const VIEWS: readonly AppView[] = ['map', 'stats', 'history'];

export interface UrlState {
  view: AppView;
  mmsi: number | null;
}

const VALID_MMSI_MIN = 100_000_000;
const VALID_MMSI_MAX = 999_999_999;

export function readUrlState(search: string = getSearch()): UrlState {
  const params = new URLSearchParams(search);
  const requested = params.get('view');
  const view: AppView = VIEWS.find((item) => item === requested) ?? 'map';
  const rawMmsi = params.get('mmsi');
  let mmsi: number | null = null;
  if (rawMmsi !== null && /^\d{9}$/.test(rawMmsi)) {
    const parsed = Number(rawMmsi);
    if (parsed >= VALID_MMSI_MIN && parsed <= VALID_MMSI_MAX) {
      mmsi = parsed;
    }
  }
  return { view, mmsi };
}

export function writeUrlState(state: UrlState, replace = false): void {
  if (typeof window === 'undefined') {
    return;
  }
  const url = new URL(window.location.href);
  if (state.view !== 'map') {
    url.searchParams.set('view', state.view);
  } else {
    url.searchParams.delete('view');
  }
  if (state.mmsi !== null) {
    url.searchParams.set('mmsi', String(state.mmsi));
  } else {
    url.searchParams.delete('mmsi');
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) {
    return;
  }
  if (replace) {
    window.history.replaceState(null, '', next);
  } else {
    window.history.pushState(null, '', next);
  }
}

function getSearch(): string {
  return typeof window !== 'undefined' ? window.location.search : '';
}
