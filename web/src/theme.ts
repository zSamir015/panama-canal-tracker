export type ThemeMode = 'light' | 'dark';
export type BasemapMode = 'map' | 'satellite';

export const THEME_STORAGE_KEY = 'panama-canal-tracker:theme';
export const BASEMAP_STORAGE_KEY = 'panama-canal-tracker:basemap';

function readStorage(key: string): string | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage.getItem(key) : null;
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string): void {
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(key, value);
    }
  } catch {
    // Modo privado o cuotas llenas: el estado en memoria sigue funcionando.
  }
}

export function readStoredTheme(): ThemeMode {
  const stored = readStorage(THEME_STORAGE_KEY);
  if (stored === 'dark' || stored === 'light') {
    return stored;
  }
  if (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  ) {
    return 'dark';
  }
  return 'light';
}

export function readStoredBasemap(): BasemapMode {
  return readStorage(BASEMAP_STORAGE_KEY) === 'satellite' ? 'satellite' : 'map';
}

export function applyDocumentTheme(theme: ThemeMode): void {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = theme;
  }
}
