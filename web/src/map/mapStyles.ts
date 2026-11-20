import type { StyleSpecification } from 'maplibre-gl';
import { DEFAULT_MAP_STYLE_URL } from '../config';
import type { BasemapMode, ThemeMode } from '../theme';

export const DARK_MAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/dark';

export const ESRI_SATELLITE_TILES_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

export const ESRI_ATTRIBUTION =
  'Tiles © Esri — Esri, Maxar, Earthstar Geographics, and the GIS User Community';

export const OPENFREEMAP_GLYPHS_URL = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';

export interface OverlayPalette {
  zoneColor: string;
  zoneFillOpacity: number;
  textHalo: string;
  trailColor: string;
  iconHalo: string;
  selectedFill: string;
  selectedStroke: string;
}

export function createSatelliteStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: OPENFREEMAP_GLYPHS_URL,
    sources: {
      'esri-satellite': {
        type: 'raster',
        tiles: [ESRI_SATELLITE_TILES_URL],
        tileSize: 256,
        maxzoom: 19,
        attribution: ESRI_ATTRIBUTION,
      },
    },
    layers: [
      {
        id: 'esri-satellite-layer',
        type: 'raster',
        source: 'esri-satellite',
      },
    ],
  };
}

export function styleIdentityKey(
  defaultStyleUrl: string,
  basemap: BasemapMode,
  theme: ThemeMode,
): string {
  if (basemap === 'satellite') {
    return 'satellite';
  }
  return theme === 'dark' && defaultStyleUrl === DEFAULT_MAP_STYLE_URL
    ? 'vector:dark'
    : `vector:custom:${defaultStyleUrl}`;
}

export function resolveMapStyle(
  defaultStyleUrl: string,
  basemap: BasemapMode,
  theme: ThemeMode,
): string | StyleSpecification {
  if (basemap === 'satellite') {
    return createSatelliteStyle();
  }
  if (theme === 'dark' && defaultStyleUrl === DEFAULT_MAP_STYLE_URL) {
    return DARK_MAP_STYLE_URL;
  }
  return defaultStyleUrl;
}

export function overlayPalette(basemap: BasemapMode, theme: ThemeMode): OverlayPalette {
  if (basemap === 'satellite' || theme === 'dark') {
    return {
      zoneColor: '#38bdf8',
      zoneFillOpacity: 0.16,
      textHalo: '#07131e',
      trailColor: '#38bdf8',
      iconHalo: '#07131e',
      selectedFill: '#fde047',
      selectedStroke: '#07131e',
    };
  }
  return {
    zoneColor: '#0b3d5c',
    zoneFillOpacity: 0.12,
    textHalo: '#ffffff',
    trailColor: '#0b3d5c',
    iconHalo: '#ffffff',
    selectedFill: '#ffd54f',
    selectedStroke: '#0b3d5c',
  };
}
