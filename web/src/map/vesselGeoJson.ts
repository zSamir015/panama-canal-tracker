import type { FeatureCollection, Point } from 'geojson';
import type { LiveVessel } from '../live/protocol';
import type { VesselState } from '../live/vesselStore';

/** Categorías de color a partir del código `ship_type` de AIS (ITU-R M.1371, tabla 53). */
export type ShipCategory =
  'cargo' | 'tanker' | 'passenger' | 'tug' | 'fishing' | 'pleasure' | 'other' | 'unknown';

export function shipCategory(shipType: number | null): ShipCategory {
  if (shipType === null) {
    return 'unknown';
  }
  if (shipType >= 70 && shipType <= 79) {
    return 'cargo';
  }
  if (shipType >= 80 && shipType <= 89) {
    return 'tanker';
  }
  if (shipType >= 60 && shipType <= 69) {
    return 'passenger';
  }
  // 31/32: remolcando; 52: remolcador; 50: práctico (en el Canal van juntos).
  if (shipType === 31 || shipType === 32 || shipType === 50 || shipType === 52) {
    return 'tug';
  }
  if (shipType === 30) {
    return 'fishing';
  }
  if (shipType === 36 || shipType === 37) {
    return 'pleasure';
  }
  return 'other';
}

export const CATEGORY_LABELS: Readonly<Record<ShipCategory, string>> = {
  cargo: 'Carga',
  tanker: 'Tanquero',
  passenger: 'Pasajeros',
  tug: 'Remolcador / práctico',
  fishing: 'Pesca',
  pleasure: 'Recreo',
  other: 'Otro',
  unknown: 'Sin tipo',
};

/** Colores de cada categoría; el mapa los usa en la capa y la leyenda. */
export const CATEGORY_COLORS: Readonly<Record<ShipCategory, string>> = {
  cargo: '#2e7d32',
  tanker: '#c62828',
  passenger: '#1565c0',
  tug: '#ef6c00',
  fishing: '#6a1b9a',
  pleasure: '#ad1457',
  other: '#455a64',
  unknown: '#90a4ae',
};

/** Tras esto sin señal AIS nueva, el buque se atenúa visualmente en el mapa. */
export const STALE_VESSEL_MS = 15 * 60_000;

export interface VesselMapFilter {
  hiddenCategories?: ReadonlySet<ShipCategory>;
  transitOnly?: boolean;
  transitMmsis?: ReadonlySet<number>;
  now?: number;
}

export interface VesselProperties {
  mmsi: number;
  category: ShipCategory;
  /** Rumbo sobre el fondo en grados; sin rumbo se pinta una baliza en vez de una silueta. */
  cog: number;
  hasCourse: boolean;
  stale: boolean;
}

export function toFeatureCollection(
  state: VesselState,
  filter?: VesselMapFilter,
): FeatureCollection<Point, VesselProperties> {
  const now = filter?.now ?? Date.now();
  const hidden = filter?.hiddenCategories;
  const transitOnly = filter?.transitOnly ?? false;
  const transitMmsis = filter?.transitMmsis;
  const features: FeatureCollection<Point, VesselProperties>['features'] = [];
  for (const vessel of state.values()) {
    const category = shipCategory(vessel.ship_type);
    if (hidden?.has(category)) {
      continue;
    }
    if (transitOnly && !transitMmsis?.has(vessel.mmsi)) {
      continue;
    }
    features.push(toFeature(vessel, category, now));
  }
  return {
    type: 'FeatureCollection',
    features,
  };
}

function toFeature(
  vessel: LiveVessel,
  category: ShipCategory,
  now: number,
): FeatureCollection<Point, VesselProperties>['features'][0] {
  const ts = Date.parse(vessel.ts);
  const stale = !Number.isNaN(ts) && now - ts > STALE_VESSEL_MS;
  return {
    type: 'Feature',
    id: vessel.mmsi,
    geometry: { type: 'Point', coordinates: [vessel.lon, vessel.lat] },
    // El nombre no va en la capa: se pinta como texto en React (ficha y tooltip), nunca HTML.
    properties: {
      mmsi: vessel.mmsi,
      category,
      cog: vessel.cog ?? 0,
      hasCourse: vessel.cog !== null,
      stale,
    },
  };
}
