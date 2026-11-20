import { useDeferredValue, useMemo, useState, type ReactNode } from 'react';
import type { LiveVessel } from '../live/protocol';
import type { VesselState } from '../live/vesselStore';
import { courseText } from '../vessels/format';
import {
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  shipCategory,
  type ShipCategory,
} from '../map/vesselGeoJson';

export type SidebarTab = 'vessels' | 'transits';

interface MapSidebarProps {
  vessels: VesselState;
  selectedMmsi: number | null;
  onSelectVessel: (vessel: LiveVessel) => void;
  onClearSelection: () => void;
  demo: boolean;
  transitsCount: number | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  detailSlot: ReactNode;
  transitsSlot: ReactNode;
}

const ALL_CATEGORIES = Object.keys(CATEGORY_LABELS) as ShipCategory[];

/**
 * Panel lateral operativo de escritorio: KPIs en tiempo real, búsqueda y filtro de buques,
 * tránsitos en curso y ficha del buque sin tapar las entradas ni los lagos del Canal. En
 * pantallas pequeñas el CSS libera la ficha y los tránsitos como hojas inferiores.
 */
export function MapSidebar({
  vessels,
  selectedMmsi,
  onSelectVessel,
  onClearSelection,
  demo,
  transitsCount,
  collapsed,
  onToggleCollapse,
  detailSlot,
  transitsSlot,
}: MapSidebarProps) {
  const [tab, setTab] = useState<SidebarTab>('vessels');
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [category, setCategory] = useState<ShipCategory | 'all'>('all');

  const vesselList = useMemo(() => {
    const items = Array.from(vessels.values());
    items.sort((a, b) => {
      const aMoving = (a.sog ?? 0) > 0.5 ? 0 : 1;
      const bMoving = (b.sog ?? 0) > 0.5 ? 0 : 1;
      if (aMoving !== bMoving) {
        return aMoving - bMoving;
      }
      return (a.name ?? String(a.mmsi)).localeCompare(b.name ?? String(b.mmsi), 'es');
    });
    return items;
  }, [vessels]);

  const metrics = useMemo(() => {
    let moving = 0;
    let speedSum = 0;
    let speedCount = 0;
    for (const vessel of vesselList) {
      if ((vessel.sog ?? 0) > 0.5) {
        moving += 1;
        if (vessel.sog !== null) {
          speedSum += vessel.sog;
          speedCount += 1;
        }
      }
    }
    const anchored = vesselList.length - moving;
    const avgKn = speedCount > 0 ? `${(speedSum / speedCount).toFixed(1)} kn` : '—';
    return { moving, anchored, avgKn };
  }, [vesselList]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<ShipCategory, number>();
    for (const vessel of vesselList) {
      const cat = shipCategory(vessel.ship_type);
      counts.set(cat, (counts.get(cat) ?? 0) + 1);
    }
    return counts;
  }, [vesselList]);

  const activeCategories = useMemo(
    () => ALL_CATEGORIES.filter((cat) => (categoryCounts.get(cat) ?? 0) > 0),
    [categoryCounts],
  );

  const effectiveTab: SidebarTab = demo ? 'vessels' : tab;
  const effectiveCategory: ShipCategory | 'all' =
    category === 'all' || (categoryCounts.get(category) ?? 0) > 0 ? category : 'all';
  const showDetail = !demo && selectedMmsi !== null;

  const filtered = useMemo(() => {
    const needle = deferredQuery.trim().toLowerCase();
    return vesselList.filter((vessel) => {
      if (effectiveCategory !== 'all' && shipCategory(vessel.ship_type) !== effectiveCategory) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const name = (vessel.name ?? '').toLowerCase();
      return name.includes(needle) || String(vessel.mmsi).includes(needle);
    });
  }, [vesselList, deferredQuery, effectiveCategory]);

  return (
    <aside
      className={collapsed ? 'sidebar sidebar--collapsed' : 'sidebar'}
      aria-label="Panel operativo"
    >
      <div className="sidebar__chrome" hidden={collapsed}>
        <div className="sidebar__head">
          <div className="sidebar__tabs" role="tablist" aria-label="Secciones del panel">
            <button
              type="button"
              role="tab"
              aria-selected={effectiveTab === 'vessels'}
              className={effectiveTab === 'vessels' ? 'sidebar__tab is-active' : 'sidebar__tab'}
              onClick={() => {
                setTab('vessels');
                if (selectedMmsi !== null) {
                  onClearSelection();
                }
              }}
            >
              Buques
              <span className="sidebar__badge">{vesselList.length}</span>
            </button>
            {!demo && (
              <button
                type="button"
                role="tab"
                aria-selected={effectiveTab === 'transits'}
                className={effectiveTab === 'transits' ? 'sidebar__tab is-active' : 'sidebar__tab'}
                onClick={() => {
                  setTab('transits');
                  if (selectedMmsi !== null) {
                    onClearSelection();
                  }
                }}
              >
                En tránsito
                {transitsCount !== null && <span className="sidebar__badge">{transitsCount}</span>}
              </button>
            )}
          </div>
          <button
            type="button"
            className="sidebar__collapse"
            aria-label={collapsed ? 'Mostrar panel lateral' : 'Ocultar panel lateral'}
            title={collapsed ? 'Mostrar panel lateral' : 'Ocultar panel lateral'}
            onClick={onToggleCollapse}
          >
            <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
              <path
                d="M10 3.5 5.5 8l4.5 4.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </div>

      <div className="sidebar__body">
        {showDetail && (
          <div className="sidebar__detail-wrap">
            <div className="sidebar__back-row">
              <button type="button" className="sidebar__back" onClick={onClearSelection}>
                <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                  <path
                    d="M10 3.5 5.5 8l4.5 4.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Volver al listado
              </button>
            </div>
            {detailSlot}
          </div>
        )}

        {!demo && (
          <div
            className={
              !showDetail && effectiveTab === 'transits'
                ? 'sidebar__transits-wrap is-visible'
                : 'sidebar__transits-wrap'
            }
          >
            {transitsSlot}
          </div>
        )}

        {!showDetail && effectiveTab === 'vessels' && (
          <div className="sidebar__vessels" aria-label="Flota en el mapa">
            <div className="sidebar__kpis" aria-label="Resumen operativo">
              <div className="sidebar__kpi">
                <span className="sidebar__kpi-label">En marcha</span>
                <strong className="sidebar__kpi-value">{metrics.moving}</strong>
              </div>
              <div className="sidebar__kpi">
                <span className="sidebar__kpi-label">Fondeados</span>
                <strong className="sidebar__kpi-value">{metrics.anchored}</strong>
              </div>
              <div className="sidebar__kpi">
                <span className="sidebar__kpi-label">Vel. media</span>
                <strong className="sidebar__kpi-value">{metrics.avgKn}</strong>
              </div>
            </div>

            <div className="sidebar__search-box">
              <label className="sidebar__search-label">
                <span className="sr-only">Buscar buques por nombre o MMSI</span>
                <svg
                  className="sidebar__search-icon"
                  viewBox="0 0 16 16"
                  width="15"
                  height="15"
                  aria-hidden="true"
                >
                  <circle
                    cx="7"
                    cy="7"
                    r="4.75"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  />
                  <path
                    d="m10.5 10.5 3.25 3.25"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
                <input
                  type="search"
                  className="sidebar__search"
                  placeholder="Buscar por nombre o MMSI…"
                  aria-label="Buscar buques por nombre o MMSI"
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                  }}
                />
                {query.length > 0 && (
                  <button
                    type="button"
                    className="sidebar__search-clear"
                    aria-label="Limpiar búsqueda"
                    onClick={() => {
                      setQuery('');
                    }}
                  >
                    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                      <path
                        d="M4.5 4.5l7 7M11.5 4.5l-7 7"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                )}
              </label>
              {activeCategories.length > 1 && (
                <div className="sidebar__chips" role="group" aria-label="Filtrar por tipo de buque">
                  <button
                    type="button"
                    className={
                      effectiveCategory === 'all' ? 'sidebar__chip is-active' : 'sidebar__chip'
                    }
                    aria-pressed={effectiveCategory === 'all'}
                    onClick={() => {
                      setCategory('all');
                    }}
                  >
                    Todos ({vesselList.length})
                  </button>
                  {activeCategories.map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      className={
                        effectiveCategory === cat ? 'sidebar__chip is-active' : 'sidebar__chip'
                      }
                      aria-pressed={effectiveCategory === cat}
                      onClick={() => {
                        setCategory(cat);
                      }}
                    >
                      <span
                        className="sidebar__chip-dot"
                        style={{ backgroundColor: CATEGORY_COLORS[cat] }}
                        aria-hidden="true"
                      />
                      {CATEGORY_LABELS[cat]} ({categoryCounts.get(cat) ?? 0})
                    </button>
                  ))}
                </div>
              )}
            </div>

            {filtered.length === 0 ? (
              <p className="sidebar__empty">
                {vesselList.length === 0
                  ? 'Sin buques visibles en este encuadre.'
                  : 'Ningún buque coincide con el filtro.'}
              </p>
            ) : (
              <ul className="sidebar__list">
                {filtered.map((vessel) => {
                  const cat = shipCategory(vessel.ship_type);
                  const title = vessel.name?.trim()
                    ? vessel.name.trim()
                    : `MMSI ${String(vessel.mmsi)}`;
                  const moving = (vessel.sog ?? 0) > 0.5;
                  return (
                    <li key={vessel.mmsi}>
                      <button
                        type="button"
                        aria-current={selectedMmsi === vessel.mmsi ? 'true' : undefined}
                        className={
                          selectedMmsi === vessel.mmsi
                            ? 'sidebar__item is-selected'
                            : 'sidebar__item'
                        }
                        onClick={() => {
                          onSelectVessel(vessel);
                        }}
                      >
                        <span
                          className="sidebar__item-dot"
                          style={{ backgroundColor: CATEGORY_COLORS[cat] }}
                          aria-hidden="true"
                        />
                        <span className="sidebar__item-main">
                          <span className="sidebar__item-name">{title}</span>
                          <span className="sidebar__item-meta">
                            <span className="mono">{vessel.mmsi}</span>
                            {' · '}
                            {CATEGORY_LABELS[cat]}
                          </span>
                        </span>
                        <span
                          className={
                            moving
                              ? 'sidebar__item-speed is-moving'
                              : 'sidebar__item-speed is-anchored'
                          }
                        >
                          {moving && vessel.sog !== null
                            ? `${vessel.sog.toFixed(1)} kn · ${courseText(vessel.cog)}`
                            : 'Fondeado'}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
