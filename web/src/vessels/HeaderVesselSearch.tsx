import { useDeferredValue, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { LiveVessel } from '../live/protocol';
import type { VesselState } from '../live/vesselStore';
import { CATEGORY_COLORS, CATEGORY_LABELS, shipCategory } from '../map/vesselGeoJson';
import { useVesselDirectory } from './queries';

export interface SearchCandidate {
  mmsi: number;
  name: string | null;
  imo: number | null;
  shipType: number | null;
  lon: number | null;
  lat: number | null;
}

interface HeaderVesselSearchProps {
  vessels: VesselState;
  token: string | null;
  demo: boolean;
  onSelect: (candidate: SearchCandidate) => void;
}

const MAX_RESULTS = 8;

/**
 * Buscador rápido global en la cabecera (atajos `/` o `⌘K`/`Ctrl+K`) por nombre, MMSI o IMO.
 */
export function HeaderVesselSearch({ vessels, token, demo, onSelect }: HeaderVesselSearchProps) {
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const directory = useVesselDirectory(demo ? null : token);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const inInput =
        target !== null &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      const isCmdK = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k';
      const isSlash =
        event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey && !inInput;
      if (isCmdK || isSlash) {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => {
      window.removeEventListener('mousedown', onPointerDown);
    };
  }, []);

  const candidates = useMemo<SearchCandidate[]>(() => {
    const byMmsi = new Map<number, SearchCandidate>();
    if (directory.data !== undefined) {
      for (const row of directory.data) {
        byMmsi.set(row.mmsi, {
          mmsi: row.mmsi,
          name: row.name,
          imo: row.imo,
          shipType: row.ship_type,
          lon: row.lon,
          lat: row.lat,
        });
      }
    }
    for (const live of vessels.values()) {
      const existing = byMmsi.get(live.mmsi);
      byMmsi.set(live.mmsi, {
        mmsi: live.mmsi,
        name: live.name ?? existing?.name ?? null,
        imo: existing?.imo ?? null,
        shipType: live.ship_type ?? existing?.shipType ?? null,
        lon: live.lon,
        lat: live.lat,
      });
    }
    return Array.from(byMmsi.values());
  }, [directory.data, vessels]);

  const results = useMemo(() => {
    const needle = deferredQuery.trim().toLowerCase();
    if (!needle) {
      return [];
    }
    const matches = candidates.filter((item) => {
      const name = (item.name ?? '').toLowerCase();
      const mmsiText = String(item.mmsi);
      const imoText = item.imo !== null ? String(item.imo) : '';
      return name.includes(needle) || mmsiText.includes(needle) || imoText.includes(needle);
    });
    matches.sort((a, b) => {
      const aLive = a.lon !== null ? 0 : 1;
      const bLive = b.lon !== null ? 0 : 1;
      if (aLive !== bLive) {
        return aLive - bLive;
      }
      return (a.name ?? String(a.mmsi)).localeCompare(b.name ?? String(b.mmsi), 'es');
    });
    return matches.slice(0, MAX_RESULTS);
  }, [candidates, deferredQuery]);

  const showDropdown = open && query.trim().length > 0;
  const clampedIndex = results.length === 0 ? 0 : Math.min(activeIndex, results.length - 1);

  const pick = (candidate: SearchCandidate) => {
    setQuery('');
    setOpen(false);
    setActiveIndex(0);
    onSelect(candidate);
  };

  return (
    <div ref={rootRef} className="header-search">
      <label className="header-search__box">
        <span className="sr-only">Buscar buque por nombre, MMSI o IMO</span>
        <svg
          className="header-search__icon"
          viewBox="0 0 16 16"
          width="14"
          height="14"
          aria-hidden="true"
        >
          <circle cx="7" cy="7" r="4.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="m10.5 10.5 3.25 3.25"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
        <input
          ref={inputRef}
          type="search"
          className="header-search__input"
          placeholder="Buscar nombre, MMSI o IMO…"
          aria-label="Buscar buque por nombre, MMSI o IMO"
          aria-expanded={showDropdown}
          aria-controls={listId}
          aria-autocomplete="list"
          role="combobox"
          value={query}
          onFocus={() => {
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setActiveIndex(0);
          }}
          onKeyDown={(event) => {
            if (!showDropdown || results.length === 0) {
              if (event.key === 'Escape') {
                setOpen(false);
                inputRef.current?.blur();
              }
              return;
            }
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setActiveIndex((prev) => (prev + 1) % results.length);
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              setActiveIndex((prev) => (prev - 1 + results.length) % results.length);
            } else if (event.key === 'Enter') {
              event.preventDefault();
              const chosen = results[clampedIndex];
              if (chosen !== undefined) {
                pick(chosen);
              }
            } else if (event.key === 'Escape') {
              event.preventDefault();
              setOpen(false);
            }
          }}
        />
        <kbd className="header-search__kbd" aria-hidden="true">
          /
        </kbd>
      </label>

      {showDropdown && (
        <ul
          id={listId}
          className="header-search__results"
          role="listbox"
          aria-label="Resultados de buques"
        >
          {results.length === 0 ? (
            <li className="header-search__empty">Sin coincidencias para «{query.trim()}».</li>
          ) : (
            results.map((item, idx) => {
              const cat = shipCategory(item.shipType);
              const label = item.name?.trim() ? item.name.trim() : `MMSI ${String(item.mmsi)}`;
              return (
                <li
                  key={item.mmsi}
                  role="option"
                  aria-selected={idx === clampedIndex}
                  className={
                    idx === clampedIndex
                      ? 'header-search__option is-highlighted'
                      : 'header-search__option'
                  }
                >
                  <button
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      pick(item);
                    }}
                  >
                    <span
                      className="header-search__dot"
                      style={{ backgroundColor: CATEGORY_COLORS[cat] }}
                      aria-hidden="true"
                    />
                    <span className="header-search__main">
                      <span className="header-search__name">{label}</span>
                      <span className="header-search__meta">
                        <span className="mono">{item.mmsi}</span>
                        {item.imo !== null && (
                          <>
                            {' · IMO '}
                            <span className="mono">{item.imo}</span>
                          </>
                        )}
                        {' · '}
                        {CATEGORY_LABELS[cat]}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}

export type { LiveVessel };
