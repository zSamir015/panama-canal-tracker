import 'maplibre-gl/dist/maplibre-gl.css';
import type { Feature, FeatureCollection, MultiLineString } from 'geojson';
import {
  type ExpressionSpecification,
  type GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
} from 'maplibre-gl';
// MapLibre busca su worker junto a su propio `.mjs`, que Vite empaqueta: hay que darle la URL
// del archivo que Vite publica (en desarrollo y en el build, siempre en el mismo origen).
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useEffect, useRef, useState } from 'react';
import { config } from '../config';
import type { Bbox } from '../live/protocol';
import type { VesselState } from '../live/vesselStore';
import type { BasemapMode, ThemeMode } from '../theme';
import { speedText } from '../vessels/format';
import {
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  shipCategory,
  toFeatureCollection,
  type VesselMapFilter,
} from './vesselGeoJson';
import canalZones from './canalZones.json';
import {
  overlayPalette,
  resolveMapStyle,
  styleIdentityKey,
  type OverlayPalette,
} from './mapStyles';
import { arrowIcon, CABIN_SCALE, cabinIcon, dotIcon } from './vesselIcons';
import {
  boundsToBbox,
  CANAL_BBOX,
  focusOffset,
  MOBILE_MEDIA_QUERY,
  MOBILE_SHEET_FRACTION,
} from './viewport';

setWorkerUrl(workerUrl);

/** Zonas de entrada del Canal (tarea 5.1). Copia exportada de `app/services/zones.py`. */
const ZONES_SOURCE_ID = 'canal-zones';
const ZONES = canalZones as unknown as FeatureCollection;

const SOURCE_ID = 'vessels';
const LAYER_ID = 'vessels';
const CABIN_LAYER_ID = 'vessels-cabin';
const TRAIL_SOURCE_ID = 'trail';
const SELECTED_LAYER_ID = 'vessel-selected';
// Los buques fondeados sin rumbo se reducen un ~28 % respecto a los que navegan para evitar
// solapamiento denso en los fondeaderos; `interpolate` con `zoom` siempre va en el nivel superior
// porque MapLibre v5 exige que `["zoom"]` sea entrada directa de `interpolate`/`step`.
const VESSEL_SIZE_EXPRESSION = [
  'interpolate',
  ['linear'],
  ['zoom'],
  9,
  ['case', ['get', 'hasCourse'], 0.78, 0.56],
  12,
  ['case', ['get', 'hasCourse'], 0.96, 0.69],
  15,
  ['case', ['get', 'hasCourse'], 1.18, 0.85],
] as unknown as ExpressionSpecification;
const CABIN_SIZE_EXPRESSION = [
  'interpolate',
  ['linear'],
  ['zoom'],
  9,
  0.78,
  12,
  0.96,
  15,
  1.18,
] as unknown as ExpressionSpecification;
const STALE_OPACITY_EXPRESSION = [
  'case',
  ['get', 'stale'],
  0.42,
  1.0,
] as unknown as ExpressionSpecification;
const EMPTY_TRAIL: Feature<MultiLineString> = {
  type: 'Feature',
  geometry: { type: 'MultiLineString', coordinates: [] },
  properties: {},
};
/** Espera tras mover el mapa antes de suscribirse: el servidor admite 20 mensajes cada 10 s. */
const VIEWPORT_DEBOUNCE_MS = 300;

const COLOR_BY_CATEGORY = [
  'match',
  ['get', 'category'],
  ...Object.entries(CATEGORY_COLORS).flat(),
  CATEGORY_COLORS.unknown,
] as unknown as ExpressionSpecification;

export interface MapFocusTarget {
  lon: number;
  lat: number;
  seq: number;
}

interface VesselMapProps {
  vessels: VesselState;
  onViewportChange: (bbox: Bbox) => void;
  selectedMmsi: number | null;
  /** Clic en un buque (su MMSI) o en el mar (`null`). */
  onSelect: (mmsi: number | null) => void;
  trail: Feature<MultiLineString> | null;
  basemap?: BasemapMode;
  theme?: ThemeMode;
  focusTarget?: MapFocusTarget | null;
  mapFilter?: VesselMapFilter;
}

interface HoverTooltip {
  x: number;
  y: number;
  mmsi: number;
  stale: boolean;
}

/** Mapa MapLibre con los buques como una sola capa GeoJSON (WebGL), sin markers DOM (ADR-0006). */
export function VesselMap({
  vessels,
  onViewportChange,
  selectedMmsi,
  onSelect,
  trail,
  basemap = 'map',
  theme = 'light',
  focusTarget = null,
  mapFilter,
}: VesselMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [hover, setHover] = useState<HoverTooltip | null>(null);
  // Lo último que se quiere pintar: si el mapa aún no ha cargado, se aplica en el `style.load`.
  const vesselsRef = useRef(vessels);
  const filterRef = useRef(mapFilter);
  const trailRef = useRef(trail);
  const selectedRef = useRef(selectedMmsi);
  const onViewportChangeRef = useRef(onViewportChange);
  const onSelectRef = useRef(onSelect);
  const paletteRef = useRef<OverlayPalette>(overlayPalette(basemap, theme));
  const styleKeyRef = useRef<string>(styleIdentityKey(config.mapStyleUrl, basemap, theme));

  useEffect(() => {
    onViewportChangeRef.current = onViewportChange;
    onSelectRef.current = onSelect;
  }, [onViewportChange, onSelect]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const map = new MapLibreMap({
      container,
      style: resolveMapStyle(config.mapStyleUrl, basemap, theme),
      bounds: [
        [CANAL_BBOX[0], CANAL_BBOX[1]],
        [CANAL_BBOX[2], CANAL_BBOX[3]],
      ],
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ visualizePitch: false }));

    let timer: ReturnType<typeof setTimeout> | undefined;
    let initialViewportReported = false;
    const reportViewport = () => {
      const bounds = map.getBounds();
      onViewportChangeRef.current(
        boundsToBbox(bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()),
      );
    };
    map.on('moveend', () => {
      clearTimeout(timer);
      timer = setTimeout(reportViewport, VIEWPORT_DEBOUNCE_MS);
    });

    const mountOverlays = () => {
      const palette = paletteRef.current;
      if (!map.hasImage('vessel-arrow')) {
        map.addImage('vessel-arrow', arrowIcon(), { sdf: true });
      }
      if (!map.hasImage('vessel-dot')) {
        map.addImage('vessel-dot', dotIcon(), { sdf: true });
      }
      if (!map.hasImage('vessel-cabin')) {
        map.addImage('vessel-cabin', cabinIcon(), { pixelRatio: CABIN_SCALE });
      }
      // Zonas de entrada, debajo de la estela y de los buques para no taparlos.
      if (!map.getSource(ZONES_SOURCE_ID)) {
        map.addSource(ZONES_SOURCE_ID, { type: 'geojson', data: ZONES });
        map.addLayer({
          id: `${ZONES_SOURCE_ID}-fill`,
          type: 'fill',
          source: ZONES_SOURCE_ID,
          paint: { 'fill-color': palette.zoneColor, 'fill-opacity': palette.zoneFillOpacity },
        });
        map.addLayer({
          id: `${ZONES_SOURCE_ID}-line`,
          type: 'line',
          source: ZONES_SOURCE_ID,
          paint: { 'line-color': palette.zoneColor, 'line-width': 1.5, 'line-dasharray': [3, 2] },
        });
        map.addLayer({
          id: `${ZONES_SOURCE_ID}-label`,
          type: 'symbol',
          source: ZONES_SOURCE_ID,
          layout: {
            'text-field': ['get', 'name'],
            'text-font': ['Noto Sans Regular'],
            'text-size': 12,
          },
          paint: {
            'text-color': palette.zoneColor,
            'text-halo-color': palette.textHalo,
            'text-halo-width': 1.5,
          },
        });
      }
      if (!map.getSource(TRAIL_SOURCE_ID)) {
        map.addSource(TRAIL_SOURCE_ID, {
          type: 'geojson',
          data: trailRef.current ?? EMPTY_TRAIL,
        });
        map.addLayer({
          id: TRAIL_SOURCE_ID,
          type: 'line',
          source: TRAIL_SOURCE_ID,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': palette.trailColor, 'line-width': 3, 'line-opacity': 0.85 },
        });
      }
      if (!map.getSource(SOURCE_ID)) {
        map.addSource(SOURCE_ID, {
          type: 'geojson',
          data: toFeatureCollection(vesselsRef.current, filterRef.current),
        });
        // Aro bajo el buque seleccionado.
        map.addLayer({
          id: SELECTED_LAYER_ID,
          type: 'circle',
          source: SOURCE_ID,
          filter: selectedFilter(selectedRef.current),
          paint: {
            'circle-radius': 16,
            'circle-color': palette.selectedFill,
            'circle-opacity': 0.55,
            'circle-stroke-color': palette.selectedStroke,
            'circle-stroke-width': 2,
          },
        });
        map.addLayer({
          id: LAYER_ID,
          type: 'symbol',
          source: SOURCE_ID,
          layout: {
            'icon-image': ['case', ['get', 'hasCourse'], 'vessel-arrow', 'vessel-dot'],
            'icon-size': VESSEL_SIZE_EXPRESSION,
            // Rumbo sobre el fondo, en grados desde el norte; la silueta gira con el mapa.
            'icon-rotate': ['get', 'cog'],
            'icon-rotation-alignment': 'map',
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
          paint: {
            'icon-color': COLOR_BY_CATEGORY,
            'icon-halo-color': palette.iconHalo,
            'icon-halo-width': 1.35,
            'icon-opacity': STALE_OPACITY_EXPRESSION,
          },
        });
        map.addLayer({
          id: CABIN_LAYER_ID,
          type: 'symbol',
          source: SOURCE_ID,
          filter: ['==', ['get', 'hasCourse'], true],
          layout: {
            'icon-image': 'vessel-cabin',
            'icon-size': CABIN_SIZE_EXPRESSION,
            'icon-rotate': ['get', 'cog'],
            'icon-rotation-alignment': 'map',
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
          paint: {
            'icon-opacity': STALE_OPACITY_EXPRESSION,
          },
        });
      }
      if (!initialViewportReported) {
        initialViewportReported = true;
        reportViewport();
      }
    };

    map.on('style.load', mountOverlays);

    map.on('click', (event) => {
      if (!map.getLayer(LAYER_ID)) {
        return;
      }
      const [feature] = map.queryRenderedFeatures(event.point, { layers: [LAYER_ID] });
      const mmsi: unknown = feature?.properties.mmsi;
      onSelectRef.current(typeof mmsi === 'number' ? mmsi : null);
    });
    map.on('mouseenter', LAYER_ID, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mousemove', LAYER_ID, (event) => {
      if (matches(MOBILE_MEDIA_QUERY)) {
        return;
      }
      const feature = event.features?.[0];
      const mmsi: unknown = feature?.properties.mmsi;
      const stale = feature?.properties.stale === true;
      if (typeof mmsi === 'number') {
        setHover({ x: event.point.x, y: event.point.y, mmsi, stale });
      }
    });
    map.on('mouseleave', LAYER_ID, () => {
      map.getCanvas().style.cursor = '';
      setHover(null);
    });
    map.on('movestart', () => {
      setHover(null);
    });

    const observer =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            map.resize();
          })
        : null;
    observer?.observe(container);

    return () => {
      clearTimeout(timer);
      observer?.disconnect();
      mapRef.current = null;
      map.remove();
    };
    // Solo se crea una instancia; los cambios posteriores de capa/tema usan `setStyle`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    paletteRef.current = overlayPalette(basemap, theme);
    const nextKey = styleIdentityKey(config.mapStyleUrl, basemap, theme);
    const map = mapRef.current;
    if (!map || nextKey === styleKeyRef.current) {
      return;
    }
    styleKeyRef.current = nextKey;
    map.setStyle(resolveMapStyle(config.mapStyleUrl, basemap, theme));
  }, [basemap, theme]);

  useEffect(() => {
    vesselsRef.current = vessels;
    filterRef.current = mapFilter;
    void mapRef.current
      ?.getSource<GeoJSONSource>(SOURCE_ID)
      ?.setData(toFeatureCollection(vessels, mapFilter));
  }, [vessels, mapFilter]);

  useEffect(() => {
    trailRef.current = trail;
    void mapRef.current?.getSource<GeoJSONSource>(TRAIL_SOURCE_ID)?.setData(trail ?? EMPTY_TRAIL);
  }, [trail]);

  useEffect(() => {
    selectedRef.current = selectedMmsi;
    const map = mapRef.current;
    if (map?.getLayer(SELECTED_LAYER_ID)) {
      map.setFilter(SELECTED_LAYER_ID, selectedFilter(selectedMmsi));
    }
    if (map && selectedMmsi !== null) {
      keepVisibleAboveSheet(map, vesselsRef.current.get(selectedMmsi));
    }
  }, [selectedMmsi]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || focusTarget === null) {
      return;
    }
    map.easeTo({
      center: [focusTarget.lon, focusTarget.lat],
      zoom: Math.max(map.getZoom(), 11.5),
      duration: matches('(prefers-reduced-motion: reduce)') ? 0 : 450,
    });
  }, [focusTarget]);

  const hoveredVessel = hover === null ? undefined : vessels.get(hover.mmsi);
  const hoveredStale = hover?.stale ?? false;
  const hoveredCategory =
    hoveredVessel !== undefined ? shipCategory(hoveredVessel.ship_type) : 'unknown';

  return (
    <div ref={containerRef} className="vessel-map">
      {hover !== null && hoveredVessel !== undefined && (
        <div className="map-tooltip" role="tooltip" style={{ left: hover.x, top: hover.y }}>
          <p className="map-tooltip__title">
            <span
              className="map-tooltip__dot"
              style={{ backgroundColor: CATEGORY_COLORS[hoveredCategory] }}
              aria-hidden="true"
            />
            {hoveredVessel.name?.trim()
              ? hoveredVessel.name.trim()
              : `MMSI ${String(hoveredVessel.mmsi)}`}
          </p>
          <p className="map-tooltip__meta">
            {CATEGORY_LABELS[hoveredCategory]}
            {' · '}
            {(hoveredVessel.sog ?? 0) > 0.5 ? speedText(hoveredVessel.sog) : 'Fondeado'}
            {hoveredStale ? ' · Señal antigua' : ''}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * En móvil la ficha es una hoja que tapa la parte de abajo del mapa (issue #125): si el buque
 * elegido queda debajo o pegado a un borde, se centra en la parte visible. En escritorio, nada.
 */
function keepVisibleAboveSheet(map: MapLibreMap, vessel: { lon: number; lat: number } | undefined) {
  if (vessel === undefined || !matches(MOBILE_MEDIA_QUERY)) {
    return;
  }
  // Al abrirse la ficha el mapa cambia de alto (desaparece la barra de tránsitos): sin `resize`,
  // MapLibre proyectaría con el tamaño anterior.
  map.resize();
  const point = map.project([vessel.lon, vessel.lat]);
  const container = map.getContainer();
  const offset = focusOffset(
    point,
    { width: container.clientWidth, height: container.clientHeight },
    MOBILE_SHEET_FRACTION,
  );
  if (offset === null) {
    return;
  }
  map.easeTo({
    center: [vessel.lon, vessel.lat],
    offset: [0, offset],
    duration: matches('(prefers-reduced-motion: reduce)') ? 0 : 400,
  });
}

function matches(query: string): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
}

function selectedFilter(mmsi: number | null): ExpressionSpecification {
  // -1 no es un MMSI: sin selección, el filtro no deja pasar ninguno.
  return ['==', ['get', 'mmsi'], mmsi ?? -1];
}
