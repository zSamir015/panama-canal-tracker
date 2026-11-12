import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWithQuery } from '../test/render';
import {
  fetchDailyStats,
  parseDailyStats,
  parseTransitDurations,
  parseWaitingTimes,
  windowParams,
  type DailyItem,
} from './api';
import { categoryText, minutesText, shortDateText } from './format';
import { axisMax, categoryTotals, dailySeries } from './series';
import { StatsView } from './StatsView';

const NOW = Date.parse('2026-11-06T12:00:00Z');

const item = (
  date: string,
  direction: DailyItem['direction'],
  transits: number,
  category = 'cargo',
) => ({ date, direction, ship_category: category, transits }) satisfies DailyItem;

const empty = { count: 0, mean_minutes: null, p50_minutes: null, p90_minutes: null };
const sample = { count: 5, mean_minutes: 180, p50_minutes: 180, p90_minutes: 276 };

const daily = {
  from: '2026-10-07T12:00:00Z',
  to: '2026-11-06T12:00:00Z',
  items: [
    item('2026-11-04', 'southbound', 2),
    item('2026-11-04', 'northbound', 1, 'tanker'),
    item('2026-11-05', 'southbound', 3, 'tanker'),
  ],
};
const durations = {
  overall: sample,
  by_direction: { southbound: sample, northbound: { ...empty, count: 0 } },
};
const waiting = {
  overall: { count: 2, mean_minutes: 90, p50_minutes: 90, p90_minutes: 114 },
  by_anchorage: {
    atlantic: { count: 2, mean_minutes: 90, p50_minutes: 90, p90_minutes: 114 },
    pacific: empty,
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parsers', () => {
  it('aceptan las respuestas de la API', () => {
    expect(parseDailyStats(daily)?.items).toHaveLength(3);
    expect(parseTransitDurations(durations)?.by_direction.southbound.count).toBe(5);
    expect(parseWaitingTimes(waiting)?.by_anchorage.pacific.count).toBe(0);
    expect(parseDailyStats({ items: [] })).toEqual({ items: [] });
  });

  it.each([
    ['un array', []],
    ['items que no es lista', { items: 3 }],
    ['fecha que no es AAAA-MM-DD', { items: [{ ...daily.items[0], date: '04/11/2026' }] }],
    ['sentido desconocido', { items: [{ ...daily.items[0], direction: 'east' }] }],
    ['tránsitos negativos', { items: [{ ...daily.items[0], transits: -1 }] }],
    ['tránsitos decimales', { items: [{ ...daily.items[0], transits: 1.5 }] }],
    ['categoría que no es texto', { items: [{ ...daily.items[0], ship_category: 7 }] }],
  ])('el diario rechaza %s', (_label, body) => {
    expect(parseDailyStats(body)).toBeNull();
  });

  it.each([
    ['sin by_direction', { overall: sample }],
    ['sin un sentido', { overall: sample, by_direction: { southbound: sample } }],
    [
      'media negativa',
      { overall: { ...sample, mean_minutes: -1 }, by_direction: durations.by_direction },
    ],
    [
      'cuenta decimal',
      { overall: { ...sample, count: 1.5 }, by_direction: durations.by_direction },
    ],
  ])('las duraciones rechazan %s', (_label, body) => {
    expect(parseTransitDurations(body)).toBeNull();
  });

  it('las esperas rechazan un fondeadero que falta', () => {
    expect(parseWaitingTimes({ overall: sample, by_anchorage: { atlantic: sample } })).toBeNull();
  });
});

describe('fetchDailyStats', () => {
  it('pide la ventana en la URL y el token solo en la cabecera', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(daily)));

    await fetchDailyStats('abc', 30, NOW, fetchImpl);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/stats/daily?${windowParams(30, NOW)}`);
    expect(init?.headers).toEqual({ Authorization: 'Bearer abc' });
  });

  it('la ventana son los últimos N días hasta ahora, en ISO', () => {
    expect(windowParams(7, NOW)).toBe(
      'from=2026-10-30T12%3A00%3A00.000Z&to=2026-11-06T12%3A00%3A00.000Z',
    );
  });
});

describe('series', () => {
  it('rellena los días sin tránsitos y suma por sentido', () => {
    const bars = dailySeries(daily.items, 4, NOW);

    expect(bars.map((bar) => bar.date)).toEqual([
      '2026-11-03',
      '2026-11-04',
      '2026-11-05',
      '2026-11-06',
    ]);
    expect(bars.map((bar) => [bar.southbound, bar.northbound])).toEqual([
      [0, 0],
      [2, 1],
      [3, 0],
      [0, 0],
    ]);
  });

  it('ignora lo que cae fuera del rango', () => {
    const bars = dailySeries([item('2026-01-01', 'southbound', 9)], 3, NOW);

    expect(bars.every((bar) => bar.southbound === 0)).toBe(true);
  });

  it('usa el día UTC aunque sean casi las 24:00', () => {
    const late = Date.parse('2026-11-06T23:59:00Z');

    expect(dailySeries([], 1, late)[0]?.date).toBe('2026-11-06');
  });

  it('suma por categoría de mayor a menor', () => {
    expect(categoryTotals(daily.items)).toEqual([
      ['tanker', 4],
      ['cargo', 2],
    ]);
    expect(
      categoryTotals([
        item('2026-11-04', 'southbound', 1, 'b'),
        item('2026-11-04', 'northbound', 1, 'a'),
      ]),
    ).toEqual([
      ['a', 1],
      ['b', 1],
    ]);
  });

  it.each([
    [0, 4],
    [3, 4],
    [7, 8],
    [11, 15],
    [23, 30],
    [101, 110],
  ])('el eje con un pico de %i llega a %i', (peak, expected) => {
    expect(axisMax([{ date: '2026-11-06', southbound: peak, northbound: 0 }])).toBe(expected);
  });
});

describe('formatos', () => {
  it('dice los minutos en horas', () => {
    expect(minutesText(null)).toBe('—');
    expect(minutesText(45)).toBe('45 min');
    expect(minutesText(60)).toBe('1 h');
    expect(minutesText(405)).toBe('6 h 45 min');
    expect(minutesText(59.6)).toBe('1 h');
  });

  it('dice la fecha corta sin pasar por la zona horaria', () => {
    expect(shortDateText('2026-11-04')).toBe('4 nov');
    expect(shortDateText('2026-01-31')).toBe('31 ene');
    expect(shortDateText('rota')).toBe('rota');
  });

  it('usa las etiquetas del mapa y deja pasar una categoría nueva', () => {
    expect(categoryText('tanker')).toBe('Tanquero');
    expect(categoryText('hovercraft')).toBe('hovercraft');
  });
});

function stubStats(
  overrides: { daily?: unknown; durations?: unknown; waiting?: unknown; status?: number } = {},
) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>((url) => {
    if (overrides.status !== undefined) {
      return Promise.resolve(Response.json({}, { status: overrides.status }));
    }
    if (url.includes('/stats/daily')) {
      return Promise.resolve(Response.json(overrides.daily ?? daily));
    }
    if (url.includes('/stats/transit-durations')) {
      return Promise.resolve(Response.json(overrides.durations ?? durations));
    }
    return Promise.resolve(Response.json(overrides.waiting ?? waiting));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('StatsView', () => {
  it('enseña el gráfico, los totales por tipo y las tablas de duración y espera', async () => {
    stubStats();
    renderWithQuery(<StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />);

    const chart = await screen.findByRole('img', { name: /6 en 30 días/ });
    expect(chart).toBeVisible();
    expect(within(chart).getAllByText(/Atlántico → Pacífico/).length).toBeGreaterThan(0);

    const categories = screen.getByRole('list', { name: 'Tránsitos por tipo de buque' });
    expect(
      within(categories)
        .getAllByRole('listitem')
        .map((entry) => entry.textContent),
    ).toEqual(['Tanquero4', 'Carga2']);

    const [durationTable, waitingTable, ...others] = await screen.findAllByRole('table');
    if (durationTable === undefined || waitingTable === undefined) {
      throw new Error('Faltan las tablas de duración y de espera');
    }
    expect(others).toHaveLength(0);
    expect(
      within(durationTable).getByRole('row', { name: /Todos 5 3 h 3 h 4 h 36 min/ }),
    ).toBeVisible();
    expect(
      within(waitingTable).getByRole('row', { name: /Fondeadero Atlántico 2 1 h 30 min/ }),
    ).toBeVisible();
  });

  it('mientras carga muestra esqueletos: un bloque para el gráfico y líneas para las tablas', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    );
    const { container } = renderWithQuery(
      <StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />,
    );

    expect(container.querySelectorAll('.skeleton--chart')).toHaveLength(1);
    expect(container.querySelectorAll('.skeleton--lines')).toHaveLength(2);
  });

  it('avisa cuando no hay datos en el periodo', async () => {
    stubStats({
      daily: { items: [] },
      durations: { overall: empty, by_direction: { southbound: empty, northbound: empty } },
      waiting: { overall: empty, by_anchorage: { atlantic: empty, pacific: empty } },
    });
    renderWithQuery(<StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />);

    expect(await screen.findByText('No hay tránsitos completados en este periodo.')).toBeVisible();
    expect(await screen.findAllByText('Sin datos en este periodo.')).toHaveLength(2);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('cambia la ventana con los botones y vuelve a pedir los datos', async () => {
    const fetchMock = stubStats();
    renderWithQuery(<StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />);
    await screen.findByRole('img');
    expect(screen.getByRole('button', { name: '30 días' })).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(screen.getByRole('button', { name: '7 días' }));

    expect(screen.getByRole('button', { name: '7 días' })).toHaveAttribute('aria-pressed', 'true');
    await vi.waitFor(() => {
      const urls = fetchMock.mock.calls.map(([url]) => url);
      expect(urls.filter((url) => url.includes('/stats/daily'))).toHaveLength(2);
    });
    expect(await screen.findByRole('img', { name: /en 7 días/ })).toBeVisible();
  });

  it('enseña el error de la API sin romper', async () => {
    stubStats({ status: 500 });
    renderWithQuery(<StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />);

    expect(await screen.findAllByRole('alert')).toHaveLength(3);
  });

  it('pide renovar el token cuando la API responde 401', async () => {
    stubStats({ status: 401 });
    const onUnauthorized = vi.fn();
    renderWithQuery(<StatsView token="abc" onUnauthorized={onUnauthorized} now={() => NOW} />);

    await vi.waitFor(() => {
      expect(onUnauthorized).toHaveBeenCalledWith('abc');
    });
  });

  it('el gráfico no lleva texto de AIS: solo números y fechas', async () => {
    stubStats();
    const { container } = renderWithQuery(
      <StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />,
    );
    await screen.findByRole('img');

    expect(container.querySelector('svg script, svg foreignObject')).toBeNull();
    expect(container.querySelectorAll('svg rect').length).toBeGreaterThan(0);
  });
});
