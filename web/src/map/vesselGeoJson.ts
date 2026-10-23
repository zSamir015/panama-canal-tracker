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

export interface VesselProperties {
  mmsi: number;
  category: ShipCategory;
  /** Rumbo sobre el fondo en grados; sin rumbo se pinta un punto en vez de una flecha. */
  cog: number;
  hasCourse: boolean;
}

export function toFeatureCollection(
  state: VesselState,
): FeatureCollection<Point, VesselProperties> {
  return {
    type: 'FeatureCollection',
    features: Array.from(state.values(), toFeature),
  };
}

function toFeature(vessel: LiveVessel): FeatureCollection<Point, VesselProperties>['features'][0] {
  return {
    type: 'Feature',
    id: vessel.mmsi,
    geometry: { type: 'Point', coordinates: [vessel.lon, vessel.lat] },
    // El nombre no va en la capa: se mostrará como texto en la ficha (4.4), nunca como HTML.
    properties: {
      mmsi: vessel.mmsi,
      category: shipCategory(vessel.ship_type),
      cog: vessel.cog ?? 0,
      hasCourse: vessel.cog !== null,
    },
  };
}
