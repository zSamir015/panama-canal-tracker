import { useEffect, useState } from 'react';
import { ApiError } from '../api/client';
import { BarChart } from './BarChart';
import { DIRECTION_COLORS } from './colors';
import type { Direction, Distribution } from './api';
import { categoryText, minutesText } from './format';
import { useDailyStats, useTransitDurations, useWaitingTimes, WINDOW_OPTIONS } from './queries';
import { axisMax, categoryTotals, dailySeries, itemsOfCategory } from './series';
import { Skeleton } from '../ui/Skeleton';

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
  // Filtros de la gráfica diaria (issue #129): solo en el cliente, con los datos ya cargados.
  const [highlight, setHighlight] = useState<Direction | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const filtering = highlight !== null || category !== null;
  const clearFilters = () => {
    setHighlight(null);
    setCategory(null);
  };

  // Si al cambiar de periodo el tipo elegido ya no aparece, el filtro se quita solo. Se ajusta
  // durante el render (el patrón de React para estado que depende de datos nuevos), no en un
  // efecto, que pintaría una vez la gráfica vacía.
  const categories = daily.data === undefined ? null : categoryTotals(daily.data.items);
  if (category !== null && categories !== null && !categories.some(([name]) => name === category)) {
    setCategory(null);
  }

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

      <article
        className="stats__card"
        onKeyDown={(event) => {
          if (event.key === 'Escape' && filtering) {
            event.stopPropagation();
            clearFilters();
          }
        }}
      >
        <div className="stats__card-header">
          <h3>Tránsitos completados por día</h3>
          {filtering && (
            <button type="button" className="stats__clear" onClick={clearFilters}>
              Quitar filtros
            </button>
          )}
        </div>
        <Loadable query={daily} skeleton={<Skeleton variant="chart" />}>
          {(data) => {
            const all = dailySeries(data.items, days, now());
            const bars =
              category === null
                ? all
                : dailySeries(itemsOfCategory(data.items, category), days, now());
            const total = data.items.reduce((sum, item) => sum + item.transits, 0);
            return total === 0 ? (
              <p className="stats__empty">No hay tránsitos completados en este periodo.</p>
            ) : (
              <>
                {/* La escala es la de todos los tránsitos: un tipo pequeño se ve pequeño. */}
                <BarChart
                  bars={bars}
                  max={axisMax(all)}
                  highlight={highlight}
                  subject={category === null ? '' : ` de tipo ${categoryText(category)}`}
                />
                <ul className="stats__legend" aria-label="Sentido">
                  {DIRECTIONS.map(([direction, label]) => (
                    <li key={direction}>
                      <button
                        type="button"
                        aria-pressed={highlight === direction}
                        className={
                          highlight !== null && highlight !== direction ? 'is-dimmed' : undefined
                        }
                        onClick={() => {
                          setHighlight((current) => (current === direction ? null : direction));
                        }}
                      >
                        <span style={{ background: DIRECTION_COLORS[direction] }} />
                        {label}
                      </button>
                    </li>
                  ))}
                </ul>
                <h4>Por tipo de buque</h4>
                <ul className="stats__categories" aria-label="Tránsitos por tipo de buque">
                  {categoryTotals(data.items).map(([name, transits]) => (
                    <li key={name}>
                      <button
                        type="button"
                        aria-pressed={category === name}
                        className={category !== null && category !== name ? 'is-dimmed' : undefined}
                        onClick={() => {
                          setCategory((current) => (current === name ? null : name));
                        }}
                      >
                        <span>{categoryText(name)}</span>
                        <span>{transits}</span>
                      </button>
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
        <Loadable query={durations} skeleton={<Skeleton lines={3} />}>
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
        <Loadable query={waiting} skeleton={<Skeleton lines={3} />}>
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

const DIRECTIONS: readonly [Direction, string][] = [
  ['southbound', 'Atlántico → Pacífico'],
  ['northbound', 'Pacífico → Atlántico'],
];

interface LoadableProps<T> {
  query: { data: T | undefined; isPending: boolean; isError: boolean; error: Error | null };
  children: (data: T) => React.ReactNode;
  /** Lo que se ve mientras llegan los datos, con la forma de lo que va a llegar. */
  skeleton: React.ReactNode;
}

function Loadable<T>({ query, children, skeleton }: LoadableProps<T>) {
  if (query.isError) {
    return (
      <p className="stats__error" role="alert">
        {query.error?.message ?? 'No se pudieron cargar las estadísticas.'}
      </p>
    );
  }
  if (query.data === undefined) {
    return <>{skeleton}</>;
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
