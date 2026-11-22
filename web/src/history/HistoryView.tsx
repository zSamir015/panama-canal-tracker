import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../api/client';
import { CATEGORY_COLORS, CATEGORY_LABELS, shipCategory } from '../map/vesselGeoJson';
import { friendlyError } from '../ui/errors';
import { Skeleton } from '../ui/Skeleton';
import type { VesselSummary } from '../vessels/api';
import { panamaDateTimeText } from '../vessels/format';
import { useSeenVessels } from '../vessels/queries';
import type { TrailWindowId } from '../vessels/trailWindow';
import { HISTORY_PERIODS, matchesFilter, MAX_ROWS, seenText } from './periods';

interface HistoryViewProps {
  token: string;
  /** La API rechazó el token (401): quien tiene la sesión lo renueva. */
  onUnauthorized: (token: string) => void;
  /** Abre el buque en el mapa, con su ficha y la estela de la ventana indicada. */
  onOpen: (vessel: VesselSummary, trail: TrailWindowId) => void;
  /** El reloj se inyecta para poder probar los «hace X». */
  now?: () => number;
}

/**
 * Historial: los buques con alguna posición en un periodo, el más reciente primero. Todo lo que
 * viene de AIS (nombre incluido) se pinta como texto con React, nunca como HTML (docs/ENGINEERING.md §8.7).
 */
export function HistoryView({ token, onUnauthorized, onOpen, now = Date.now }: HistoryViewProps) {
  const [periodId, setPeriodId] = useState(HISTORY_PERIODS[0]?.id ?? '24h');
  const [filter, setFilter] = useState('');
  const period = HISTORY_PERIODS.find((item) => item.id === periodId) ?? HISTORY_PERIODS[0];
  const seen = useSeenVessels(token, periodId, period?.ms ?? 24 * 3_600_000);

  const unauthorized = seen.error instanceof ApiError && seen.error.status === 401;
  useEffect(() => {
    if (unauthorized) {
      onUnauthorized(token);
    }
  }, [unauthorized, token, onUnauthorized]);

  const needle = filter.trim().toLowerCase();
  const matches = useMemo(
    () => (seen.data ?? []).filter((vessel) => matchesFilter(vessel, needle)),
    [seen.data, needle],
  );
  const shown = matches.slice(0, MAX_ROWS);
  const current = now();

  return (
    <section className="stats history" aria-label="Historial">
      <div className="stats__container">
        <header className="stats__header">
          <h2>Historial de buques</h2>
          <div role="group" aria-label="Periodo" className="stats__window">
            {HISTORY_PERIODS.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={item.id === periodId}
                onClick={() => {
                  setPeriodId(item.id);
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
        </header>

        <label className="history__filter">
          <span className="sr-only">Filtrar por nombre, MMSI o IMO</span>
          <input
            type="search"
            placeholder="Filtrar por nombre, MMSI o IMO…"
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value);
            }}
          />
        </label>

        {seen.isPending ? (
          <Skeleton lines={5} />
        ) : seen.isError ? (
          <p className="stats__error" role="alert">
            {friendlyError(seen.error, 'No se pudo cargar el historial.')}
          </p>
        ) : (
          <>
            <p className="stats__note" role="status">
              {seen.data.length === 0
                ? `No hay buques con posiciones en las últimas ${period?.label ?? ''}.`
                : `${String(matches.length)} de ${String(seen.data.length)} buques vistos en las últimas ${period?.label ?? ''}. Pulsa uno para ver su ruta en el mapa.`}
            </p>
            <ul className="history__list">
              {shown.map((vessel) => {
                const category = shipCategory(vessel.ship_type);
                return (
                  <li key={vessel.mmsi}>
                    <button
                      type="button"
                      className="history__row"
                      onClick={() => {
                        onOpen(vessel, period?.trail ?? '24h');
                      }}
                    >
                      <span
                        className="history__dot"
                        style={{ background: CATEGORY_COLORS[category] }}
                        aria-hidden="true"
                      />
                      <span className="history__name">
                        {vessel.name ?? `MMSI ${String(vessel.mmsi)}`}
                      </span>
                      <span className="history__meta">
                        {vessel.name !== null && `${String(vessel.mmsi)} · `}
                        {CATEGORY_LABELS[category]}
                      </span>
                      <time
                        className="history__seen"
                        dateTime={vessel.last_seen_at ?? undefined}
                        title={panamaDateTimeText(vessel.last_seen_at)}
                      >
                        {seenText(vessel.last_seen_at, current)}
                      </time>
                    </button>
                  </li>
                );
              })}
            </ul>
            {matches.length > shown.length && (
              <p className="stats__note">
                Se enseñan los {String(MAX_ROWS)} más recientes: usa el filtro para encontrar otro.
              </p>
            )}
          </>
        )}
        <p className="stats__note">
          Cobertura AIS terrestre parcial: solo aparecen los buques de los que se recibió alguna
          posición.
        </p>
      </div>
    </section>
  );
}
