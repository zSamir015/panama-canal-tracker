import 'maplibre-gl/dist/maplibre-gl.css';
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
}

/** Mapa MapLibre con los buques como una sola capa GeoJSON (WebGL), sin markers DOM (ADR-0006). */
export function VesselMap({ vessels, onViewportChange }: VesselMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const vesselsRef = useRef(vessels);
  const onViewportChangeRef = useRef(onViewportChange);

  useEffect(() => {
    onViewportChangeRef.current = onViewportChange;
  }, [onViewportChange]);

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
      map.addSource(SOURCE_ID, {
        type: 'geojson',
        data: toFeatureCollection(vesselsRef.current),
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

  return <div ref={containerRef} className="vessel-map" />;
}
