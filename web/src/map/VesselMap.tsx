import 'maplibre-gl/dist/maplibre-gl.css';
import type { Feature, MultiLineString } from 'geojson';
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
import { useEffect, useRef } from 'react';
import { config } from '../config';
import type { Bbox } from '../live/protocol';
import type { VesselState } from '../live/vesselStore';
import { CATEGORY_COLORS, toFeatureCollection } from './vesselGeoJson';
import { arrowIcon, dotIcon } from './vesselIcons';
import { boundsToBbox, CANAL_BBOX } from './viewport';

setWorkerUrl(workerUrl);

const SOURCE_ID = 'vessels';
const LAYER_ID = 'vessels';
const TRAIL_SOURCE_ID = 'trail';
const SELECTED_LAYER_ID = 'vessel-selected';
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

interface VesselMapProps {
  vessels: VesselState;
  onViewportChange: (bbox: Bbox) => void;
  selectedMmsi: number | null;
  /** Clic en un buque (su MMSI) o en el mar (`null`). */
  onSelect: (mmsi: number | null) => void;
  trail: Feature<MultiLineString> | null;
}

/** Mapa MapLibre con los buques como una sola capa GeoJSON (WebGL), sin markers DOM (ADR-0006). */
export function VesselMap({
  vessels,
  onViewportChange,
  selectedMmsi,
  onSelect,
  trail,
}: VesselMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Lo último que se quiere pintar: si el mapa aún no ha cargado, se aplica en el `load`.
  const vesselsRef = useRef(vessels);
  const trailRef = useRef(trail);
  const selectedRef = useRef(selectedMmsi);
  const onViewportChangeRef = useRef(onViewportChange);
  const onSelectRef = useRef(onSelect);

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
      style: config.mapStyleUrl,
      bounds: [
        [CANAL_BBOX[0], CANAL_BBOX[1]],
        [CANAL_BBOX[2], CANAL_BBOX[3]],
      ],
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ visualizePitch: false }));

    let timer: ReturnType<typeof setTimeout> | undefined;
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

    map.on('load', () => {
      map.addImage('vessel-arrow', arrowIcon(), { sdf: true });
      map.addImage('vessel-dot', dotIcon(), { sdf: true });
      map.addSource(TRAIL_SOURCE_ID, { type: 'geojson', data: trailRef.current ?? EMPTY_TRAIL });
      map.addLayer({
        id: TRAIL_SOURCE_ID,
        type: 'line',
        source: TRAIL_SOURCE_ID,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#0b3d5c', 'line-width': 3, 'line-opacity': 0.75 },
      });
      map.addSource(SOURCE_ID, {
        type: 'geojson',
        data: toFeatureCollection(vesselsRef.current),
      });
      // Aro bajo el buque seleccionado.
      map.addLayer({
        id: SELECTED_LAYER_ID,
        type: 'circle',
        source: SOURCE_ID,
        filter: selectedFilter(selectedRef.current),
        paint: {
          'circle-radius': 16,
          'circle-color': '#ffd54f',
          'circle-opacity': 0.5,
          'circle-stroke-color': '#0b3d5c',
          'circle-stroke-width': 2,
        },
      });
      map.addLayer({
        id: LAYER_ID,
        type: 'symbol',
        source: SOURCE_ID,
        layout: {
          'icon-image': ['case', ['get', 'hasCourse'], 'vessel-arrow', 'vessel-dot'],
          'icon-size': 0.75,
          // Rumbo sobre el fondo, en grados desde el norte; la flecha gira con el mapa.
          'icon-rotate': ['get', 'cog'],
          'icon-rotation-alignment': 'map',
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
        paint: {
          'icon-color': COLOR_BY_CATEGORY,
          'icon-halo-color': '#ffffff',
          'icon-halo-width': 1,
        },
      });
      reportViewport();
    });

    map.on('click', (event) => {
      const [feature] = map.queryRenderedFeatures(event.point, { layers: [LAYER_ID] });
      const mmsi: unknown = feature?.properties.mmsi;
      onSelectRef.current(typeof mmsi === 'number' ? mmsi : null);
    });
    map.on('mouseenter', LAYER_ID, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', LAYER_ID, () => {
      map.getCanvas().style.cursor = '';
    });

    return () => {
      clearTimeout(timer);
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    vesselsRef.current = vessels;
    void mapRef.current?.getSource<GeoJSONSource>(SOURCE_ID)?.setData(toFeatureCollection(vessels));
  }, [vessels]);

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
  }, [selectedMmsi]);

  return <div ref={containerRef} className="vessel-map" />;
}

function selectedFilter(mmsi: number | null): ExpressionSpecification {
  // -1 no es un MMSI: sin selección, el filtro no deja pasar ninguno.
  return ['==', ['get', 'mmsi'], mmsi ?? -1];
}
