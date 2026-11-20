import { useId, useState } from 'react';
import { CATEGORY_COLORS, CATEGORY_LABELS, type ShipCategory } from './vesselGeoJson';

interface MapLegendProps {
  hiddenCategories?: ReadonlySet<ShipCategory>;
  onToggleCategory?: (category: ShipCategory) => void;
  transitOnly?: boolean;
  onToggleTransitOnly?: () => void;
  showTransitFilter?: boolean;
}

const EMPTY_SET: ReadonlySet<ShipCategory> = new Set();

/**
 * Leyenda interactiva por tipo de buque con filtros en vivo ("Solo en tránsito" y ocultar/mostrar
 * categorías). En móvil empieza plegada; en escritorio se muestra abierta.
 */
export function MapLegend({
  hiddenCategories = EMPTY_SET,
  onToggleCategory,
  transitOnly = false,
  onToggleTransitOnly,
  showTransitFilter = false,
}: MapLegendProps) {
  const [collapsed, setCollapsed] = useState(true);
  const listId = useId();
  const interactive = onToggleCategory !== undefined;

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
      <div className="map-legend__header">
        <p className="map-legend__title" aria-hidden="true">
          Tipos de buque
        </p>
        {showTransitFilter && onToggleTransitOnly !== undefined && (
          <button
            type="button"
            className="map-legend__transit-toggle"
            aria-pressed={transitOnly}
            onClick={onToggleTransitOnly}
          >
            Solo en tránsito
          </button>
        )}
      </div>
      <ul id={listId} className="map-legend__list" aria-label="Tipos de buque">
        {Object.entries(CATEGORY_LABELS).map(([rawCategory, label]) => {
          const category = rawCategory as ShipCategory;
          const visible = !hiddenCategories.has(category);
          return (
            <li key={category}>
              {interactive ? (
                <button
                  type="button"
                  className={
                    visible ? 'map-legend__item' : 'map-legend__item map-legend__item--hidden'
                  }
                  aria-pressed={visible}
                  onClick={() => {
                    onToggleCategory(category);
                  }}
                >
                  <span
                    className="map-legend__swatch"
                    style={{ background: CATEGORY_COLORS[category] }}
                  />
                  {label}
                </button>
              ) : (
                <>
                  <span
                    className="map-legend__swatch"
                    style={{ background: CATEGORY_COLORS[category] }}
                  />
                  {label}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
