import { useEffect, useState } from 'react';
import { ApiError } from '../api/client';
import { BarChart } from './BarChart';
import { DIRECTION_COLORS } from './colors';
import type { Distribution } from './api';
import { categoryText, minutesText } from './format';
import { useDailyStats, useTransitDurations, useWaitingTimes, WINDOW_OPTIONS } from './queries';
import { categoryTotals, dailySeries } from './series';

interface StatsViewProps {
  token: string;
  /** La API rechazó el token (401): quien tiene la sesión lo renueva. */
  onUnauthorized: (token: string) => void;
  /** El reloj se inyecta para poder probar el eje de fechas. */
  now?: () => number;
}

export function StatsView({ token, onUnauthorized, now = Date.now }: StatsViewProps) {
  const [days, setDays] = useState<number>(30);
  const daily = useDailyStats(token, days);
  const durations = useTransitDurations(token, days);
  const waiting = useWaitingTimes(token, days);

  const unauthorized = [daily, durations, waiting].some(
    (query) => query.error instanceof ApiError && query.error.status === 401,
  );
  useEffect(() => {
    if (unauthorized) {
      onUnauthorized(token);
    }
  }, [unauthorized, token, onUnauthorized]);

  return (
    <section className="stats" aria-label="Estadísticas">
      <header className="stats__header">
        <h2>Estadísticas del Canal</h2>
        <div role="group" aria-label="Periodo" className="stats__window">
          {WINDOW_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={option === days}
              onClick={() => {
                setDays(option);
              }}
            >
              {option} días
            </button>
          ))}
        </div>
      </header>

      <article className="stats__card">
        <h3>Tránsitos completados por día</h3>
        <Loadable query={daily}>
          {(data) => {
            const bars = dailySeries(data.items, days, now());
            const total = data.items.reduce((sum, item) => sum + item.transits, 0);
            return total === 0 ? (
              <p className="stats__empty">No hay tránsitos completados en este periodo.</p>
            ) : (
              <>
                <BarChart bars={bars} />
                <ul className="stats__legend" aria-label="Sentido">
                  <li>
                    <span style={{ background: DIRECTION_COLORS.southbound }} />
                    Atlántico → Pacífico
                  </li>
                  <li>
                    <span style={{ background: DIRECTION_COLORS.northbound }} />
                    Pacífico → Atlántico
                  </li>
                </ul>
                <h4>Por tipo de buque</h4>
                <ul className="stats__categories" aria-label="Tránsitos por tipo de buque">
                  {categoryTotals(data.items).map(([category, transits]) => (
                    <li key={category}>
                      <span>{categoryText(category)}</span>
                      <span>{transits}</span>
                    </li>
                  ))}
                </ul>
              </>
            );
          }}
        </Loadable>
      </article>

      <article className="stats__card">
        <h3>Duración del tránsito</h3>
        <Loadable query={durations}>
          {(data) => (
            <DistributionTable
              total={data.overall}
              rows={[
                ['Atlántico → Pacífico', data.by_direction.southbound],
                ['Pacífico → Atlántico', data.by_direction.northbound],
              ]}
            />
          )}
        </Loadable>
      </article>

      <article className="stats__card">
        <h3>Espera en fondeo antes de entrar</h3>
        <Loadable query={waiting}>
          {(data) => (
            <DistributionTable
              total={data.overall}
              rows={[
                ['Fondeadero Atlántico', data.by_anchorage.atlantic],
                ['Fondeadero Pacífico', data.by_anchorage.pacific],
              ]}
            />
          )}
        </Loadable>
        <p className="stats__note">
          Solo los tránsitos en los que se detectó al buque esperando en un fondeadero.
        </p>
      </article>
    </section>
  );
}

interface LoadableProps<T> {
  query: { data: T | undefined; isPending: boolean; isError: boolean; error: Error | null };
  children: (data: T) => React.ReactNode;
}

function Loadable<T>({ query, children }: LoadableProps<T>) {
  if (query.isError) {
    return (
      <p className="stats__error" role="alert">
        {query.error?.message ?? 'No se pudieron cargar las estadísticas.'}
      </p>
    );
  }
  if (query.data === undefined) {
    return <p>Cargando…</p>;
  }
  return <>{children(query.data)}</>;
}

interface DistributionTableProps {
  total: Distribution;
  rows: [string, Distribution][];
}

function DistributionTable({ total, rows }: DistributionTableProps) {
  if (total.count === 0) {
    return <p className="stats__empty">Sin datos en este periodo.</p>;
  }
  return (
    <table className="stats__table">
      <thead>
        <tr>
          <th scope="col">Grupo</th>
          <th scope="col">Tránsitos</th>
          <th scope="col">Media</th>
          <th scope="col">Mediana</th>
          <th scope="col">P90</th>
        </tr>
      </thead>
      <tbody>
        {[['Todos', total] as [string, Distribution], ...rows].map(([label, row]) => (
          <tr key={label}>
            <th scope="row">{label}</th>
            <td>{row.count}</td>
            <td>{minutesText(row.mean_minutes)}</td>
            <td>{minutesText(row.p50_minutes)}</td>
            <td>{minutesText(row.p90_minutes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
