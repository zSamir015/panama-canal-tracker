import { CATEGORY_COLORS, CATEGORY_LABELS, type ShipCategory } from './vesselGeoJson';

export function MapLegend() {
  return (
    <ul className="map-legend" aria-label="Tipos de buque">
      {Object.entries(CATEGORY_LABELS).map(([category, label]) => (
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
