import { useId, useState } from 'react';
import { CATEGORY_COLORS, CATEGORY_LABELS, type ShipCategory } from './vesselGeoJson';

/**
 * Leyenda de colores por tipo de buque. En móvil empieza plegada en una pastilla para no tapar el
 * mapa; en escritorio el CSS oculta el botón y la lista se ve siempre (issue #123).
 */
export function MapLegend() {
  const [collapsed, setCollapsed] = useState(true);
  const listId = useId();

  return (
    <div className={collapsed ? 'map-legend map-legend--collapsed' : 'map-legend'}>
      <button
        type="button"
        className="map-legend__toggle"
        aria-expanded={!collapsed}
        aria-controls={listId}
        onClick={() => {
          setCollapsed((value) => !value);
        }}
      >
        Leyenda
      </button>
      <ul id={listId} className="map-legend__list" aria-label="Tipos de buque">
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
    </div>
  );
}
