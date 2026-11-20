import { describe, expect, it } from 'vitest';
import { DEFAULT_MAP_STYLE_URL } from '../config';
import {
  applyDocumentTheme,
  BASEMAP_STORAGE_KEY,
  readStoredBasemap,
  readStoredTheme,
  THEME_STORAGE_KEY,
  writeStorage,
} from '../theme';
import {
  createSatelliteStyle,
  DARK_MAP_STYLE_URL,
  ESRI_ATTRIBUTION,
  ESRI_SATELLITE_TILES_URL,
  OPENFREEMAP_GLYPHS_URL,
  overlayPalette,
  resolveMapStyle,
  styleIdentityKey,
} from './mapStyles';

describe('theme & basemap storage', () => {
  it('usa tema claro y mapa estándar por defecto', () => {
    window.localStorage.removeItem(THEME_STORAGE_KEY);
    window.localStorage.removeItem(BASEMAP_STORAGE_KEY);
    expect(readStoredTheme()).toBe('light');
    expect(readStoredBasemap()).toBe('map');
  });

  it('persiste tema oscuro y capa satelital en localStorage y en el documento', () => {
    writeStorage(THEME_STORAGE_KEY, 'dark');
    writeStorage(BASEMAP_STORAGE_KEY, 'satellite');
    expect(readStoredTheme()).toBe('dark');
    expect(readStoredBasemap()).toBe('satellite');

    applyDocumentTheme('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    applyDocumentTheme('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});

describe('mapStyles', () => {
  it('resuelve estilo claro, oscuro y satélite sin API keys', () => {
    expect(resolveMapStyle(DEFAULT_MAP_STYLE_URL, 'map', 'light')).toBe(DEFAULT_MAP_STYLE_URL);
    expect(resolveMapStyle(DEFAULT_MAP_STYLE_URL, 'map', 'dark')).toBe(DARK_MAP_STYLE_URL);
    // Si el usuario fijó un estilo propio, se respeta en modo vectorial.
    expect(resolveMapStyle('https://tiles.example.com/custom.json', 'map', 'dark')).toBe(
      'https://tiles.example.com/custom.json',
    );

    const satellite = resolveMapStyle(DEFAULT_MAP_STYLE_URL, 'satellite', 'light');
    expect(typeof satellite).toBe('object');
    if (typeof satellite === 'object') {
      expect(satellite.version).toBe(8);
      expect(satellite.glyphs).toBe(OPENFREEMAP_GLYPHS_URL);
      const source = satellite.sources['esri-satellite'];
      expect(source).toMatchObject({
        type: 'raster',
        tiles: [ESRI_SATELLITE_TILES_URL],
        attribution: ESRI_ATTRIBUTION,
      });
    }
  });

  it('mantiene la identidad de satélite al cambiar solo entre tema claro y oscuro', () => {
    expect(styleIdentityKey(DEFAULT_MAP_STYLE_URL, 'satellite', 'light')).toBe('satellite');
    expect(styleIdentityKey(DEFAULT_MAP_STYLE_URL, 'satellite', 'dark')).toBe('satellite');
    expect(createSatelliteStyle().layers).toHaveLength(1);
    expect(overlayPalette('satellite', 'light').trailColor).toBe('#38bdf8');
    expect(overlayPalette('map', 'light').trailColor).toBe('#0b3d5c');
  });
});
