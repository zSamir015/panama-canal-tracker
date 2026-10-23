import { CATEGORY_COLORS, type ShipCategory } from './vesselGeoJson';

const LABELS: Record<ShipCategory, string> = {
  cargo: 'Carga',
  tanker: 'Tanquero',
  passenger: 'Pasajeros',
  tug: 'Remolcador / práctico',
  fishing: 'Pesca',
  pleasure: 'Recreo',
  other: 'Otro',
  unknown: 'Sin tipo',
};

export function MapLegend() {
  return (
    <ul className="map-legend" aria-label="Tipos de buque">
      {Object.entries(LABELS).map(([category, label]) => (
        <li key={category}>
          <span
            className="map-legend__swatch"
            style={{ background: CATEGORY_COLORS[category as ShipCategory] }}
          />
          {label}
        </li>
      ))}
    </ul>
  );
}
