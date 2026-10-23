/** Configuración pública del frontend, leída de las variables `VITE_*` al compilar. */
export interface AppConfig {
  /** Origen de la API (sin barra final). Vacío: la misma del frontend, detrás del proxy. */
  apiUrl: string;
  /** Estilo de tiles de MapLibre (ADR-0010). */
  mapStyleUrl: string;
}

/** OpenFreeMap: sin key ni cuenta, así que no hay nada que proteger en el frontend (ADR-0010). */
export const DEFAULT_MAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';

export function readConfig(env: ImportMetaEnv): AppConfig {
  return {
    apiUrl: normalizeUrl(env.VITE_API_URL) ?? '',
    mapStyleUrl: normalizeUrl(env.VITE_MAP_STYLE_URL) ?? DEFAULT_MAP_STYLE_URL,
  };
}

function normalizeUrl(value: string | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) {
    return null;
  }
  const url = new URL(trimmed);
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error(`URL no admitida en la configuración: ${url.protocol}`);
  }
  if (url.username || url.password) {
    // Lo que va en VITE_* es público: una URL con credenciales sería una fuga.
    throw new Error('La URL de la configuración no puede llevar credenciales');
  }
  return trimmed.replace(/\/+$/, '');
}

export const config = readConfig(import.meta.env);
