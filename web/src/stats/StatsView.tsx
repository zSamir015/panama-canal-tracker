import { useEffect, useState } from 'react';
import { ApiError } from '../api/client';
import { friendlyError } from '../ui/errors';
import { Skeleton } from '../ui/Skeleton';
import { BarChart } from './BarChart';
import { DIRECTION_COLORS } from './colors';
import type { DailyItem, Direction, Distribution } from './api';
import { categoryText, minutesText } from './format';
import {
  useDailyStats,
  usePreviousTransitDurations,
  usePreviousWaitingTimes,
  useTransitDurations,
  useWaitingTimes,
  WINDOW_OPTIONS,
} from './queries';
import { axisMax, categoryTotals, dailySeries, itemsOfCategory } from './series';

interface StatsViewProps {
  token: string;
  /** La API rechazó el token (401): quien tiene la sesión lo renueva. */
  onUnauthorized: (token: string) => void;
  /** El reloj se inyecta para poder probar el eje de fechas. */
  now?: () => number;
}

const DAY_MS = 86_400_000;

export function StatsView({ token, onUnauthorized, now = Date.now }: StatsViewProps) {
  const [days, setDays] = useState<number>(30);
  // Pide 2 × days en una sola consulta para comparar los totales diarios con el periodo previo.
  const daily = useDailyStats(token, days * 2);
  const durations = useTransitDurations(token, days);
  const waiting = useWaitingTimes(token, days);
  const prevDurations = usePreviousTransitDurations(token, days);
  const prevWaiting = usePreviousWaitingTimes(token, days);
  // Filtros de la gráfica diaria (issue #129): solo en el cliente, con los datos ya cargados.
  const [highlight, setHighlight] = useState<Direction | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const filtering = highlight !== null || category !== null;
  const clearFilters = () => {
    setHighlight(null);
    setCategory(null);
  };

  const nowMs = now();
  const { currentItems, previousItems } =
    daily.data === undefined
      ? { currentItems: undefined, previousItems: undefined }
      : splitDailyWindows(daily.data.items, days, nowMs);

  // Si al cambiar de periodo el tipo elegido ya no aparece, el filtro se quita solo. Se ajusta
  // durante el render (el patrón de React para estado que depende de datos nuevos), no en un
  // efecto, que pintaría una vez la gráfica vacía.
  const categories = currentItems === undefined ? null : categoryTotals(currentItems);
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

  const currentTotal = currentItems?.reduce((sum, item) => sum + item.transits, 0);
  const previousTotal = previousItems?.reduce((sum, item) => sum + item.transits, 0);
  const currentDurationP50 = durations.data?.overall.p50_minutes;
  const previousDurationP50 = prevDurations.data?.overall.p50_minutes;
  const currentWaitingP50 = waiting.data?.overall.p50_minutes;
  const previousWaitingP50 = prevWaiting.data?.overall.p50_minutes;

  return (
    <section className="stats" aria-label="Estadísticas">
      <div className="stats__container">
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

        <section className="stats__kpis" aria-label="Resumen del periodo">
          <article className="stats__kpi">
            <p className="stats__kpi-label">Tránsitos ({days} días)</p>
            <p className="stats__kpi-value">
              {currentTotal === undefined ? '—' : String(currentTotal)}
            </p>
            <p className="stats__kpi-delta">{countDeltaText(currentTotal, previousTotal)}</p>
          </article>
          <article className="stats__kpi">
            <p className="stats__kpi-label">Duración mediana</p>
            <p className="stats__kpi-value">
              {currentDurationP50 === undefined ? '—' : minutesText(currentDurationP50)}
            </p>
            <p className="stats__kpi-delta">
              {minutesDeltaText(currentDurationP50, previousDurationP50)}
            </p>
          </article>
          <article className="stats__kpi">
            <p className="stats__kpi-label">Espera mediana en fondeo</p>
            <p className="stats__kpi-value">
              {currentWaitingP50 === undefined ? '—' : minutesText(currentWaitingP50)}
            </p>
            <p className="stats__kpi-delta">
              {minutesDeltaText(currentWaitingP50, previousWaitingP50)}
            </p>
          </article>
        </section>

        <p className="stats__coverage-note">
          Cobertura AIS terrestre parcial: los conteos y medianas reflejan solo los tránsitos con
          recepción continua en esclusas y fondeaderos.
        </p>

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
          <Loadable
            query={daily}
            skeleton={<Skeleton variant="chart" />}
            fallbackError="No se pudieron cargar los tránsitos diarios."
          >
            {() => {
              const items = currentItems ?? [];
              const all = dailySeries(items, days, nowMs);
              const bars =
                category === null
                  ? all
                  : dailySeries(itemsOfCategory(items, category), days, nowMs);
              const total = items.reduce((sum, item) => sum + item.transits, 0);
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
                    {categoryTotals(items).map(([name, transits]) => (
                      <li key={name}>
                        <button
                          type="button"
                          aria-pressed={category === name}
                          className={
                            category !== null && category !== name ? 'is-dimmed' : undefined
                          }
                          onClick={() => {
                            setCategory((current) => (current === name ? null : name));
                          }}
                        >
                          <span>{categoryText(name)}</span>
                          <span className="stats__category-count">{transits}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              );
            }}
          </Loadable>
        </article>

        <div className="stats__grid">
          <article className="stats__card">
            <h3>Duración del tránsito</h3>
            <Loadable
              query={durations}
              skeleton={<Skeleton lines={3} />}
              fallbackError="No se pudo cargar la duración de los tránsitos."
            >
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
            <Loadable
              query={waiting}
              skeleton={<Skeleton lines={3} />}
              fallbackError="No se pudieron cargar los tiempos de espera."
            >
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
        </div>
      </div>
    </section>
  );
}

function splitDailyWindows(
  items: readonly DailyItem[],
  days: number,
  nowMs: number,
): { currentItems: DailyItem[]; previousItems: DailyItem[] } {
  const lastDay = Math.floor(nowMs / DAY_MS);
  const cutoffDate = new Date((lastDay - days + 1) * DAY_MS).toISOString().slice(0, 10);
  const endDate = new Date(lastDay * DAY_MS).toISOString().slice(0, 10);
  const prevStartDate = new Date((lastDay - days * 2 + 1) * DAY_MS).toISOString().slice(0, 10);
  const currentItems: DailyItem[] = [];
  const previousItems: DailyItem[] = [];
  for (const item of items) {
    if (item.date >= cutoffDate && item.date <= endDate) {
      currentItems.push(item);
    } else if (item.date >= prevStartDate && item.date < cutoffDate) {
      previousItems.push(item);
    }
  }
  return { currentItems, previousItems };
}

function countDeltaText(current: number | undefined, previous: number | undefined): string {
  if (current === undefined || previous === undefined) {
    return 'Comparando con periodo anterior';
  }
  const diff = current - previous;
  if (diff === 0) {
    return 'Sin cambios vs periodo anterior';
  }
  const sign = diff > 0 ? `+${String(diff)}` : `−${String(Math.abs(diff))}`;
  if (previous === 0) {
    return `${sign} vs periodo anterior`;
  }
  const pct = Math.round((diff / previous) * 100);
  const pctSign = pct > 0 ? `+${String(pct)}` : `−${String(Math.abs(pct))}`;
  return `${sign} (${pctSign} %) vs periodo anterior`;
}

function minutesDeltaText(
  current: number | null | undefined,
  previous: number | null | undefined,
): string {
  if (current === undefined || current === null || previous === undefined || previous === null) {
    return 'Sin referencia anterior';
  }
  const diff = Math.round(current - previous);
  if (diff === 0) {
    return 'Igual que el periodo anterior';
  }
  const formatted = minutesText(Math.abs(diff));
  const prefix = diff > 0 ? '+' : '−';
  return `${prefix}${formatted} vs periodo anterior`;
}

const DIRECTIONS: readonly [Direction, string][] = [
  ['southbound', 'Atlántico → Pacífico'],
  ['northbound', 'Pacífico → Atlántico'],
];

interface LoadableProps<T> {
  query: {
    data: T | undefined;
    isPending: boolean;
    isError: boolean;
    error: Error | null;
    refetch: () => Promise<unknown>;
  };
  children: (data: T) => React.ReactNode;
  /** Lo que se ve mientras llegan los datos, con la forma de lo que va a llegar. */
  skeleton: React.ReactNode;
  fallbackError: string;
}

function Loadable<T>({ query, children, skeleton, fallbackError }: LoadableProps<T>) {
  if (query.isError) {
    return (
      <div className="panel__error">
        <p className="stats__error" role="alert">
          {friendlyError(query.error, fallbackError)}
        </p>
        <button
          type="button"
          className="panel__retry"
          onClick={() => {
            void query.refetch();
          }}
        >
          Reintentar
        </button>
      </div>
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
