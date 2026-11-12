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
import { axisMax, categoryTotals, dailySeries, itemsOfCategory } from './series';
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

describe('itemsOfCategory', () => {
  it('sin categoría devuelve todos; con categoría, solo los suyos', () => {
    expect(itemsOfCategory(daily.items, null)).toEqual(daily.items);
    expect(itemsOfCategory(daily.items, 'tanker')).toEqual([daily.items[1], daily.items[2]]);
    expect(itemsOfCategory(daily.items, 'fishing')).toEqual([]);
  });
});

describe('StatsView: leyenda y filtros (issue #129)', () => {
  // Un tipo pequeño (carga, 1) frente a uno grande (tanquero, 12): así se nota si la escala cambia.
  const skewed = {
    ...daily,
    items: [item('2026-11-04', 'southbound', 12, 'tanker'), item('2026-11-05', 'southbound', 1)],
  };

  async function renderStats(overrides: Parameters<typeof stubStats>[0] = {}) {
    stubStats(overrides);
    renderWithQuery(<StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />);
    return screen.findByRole('img', { name: /Tránsitos/ });
  }

  const bars = (chart: HTMLElement, direction: 'southbound' | 'northbound') => [
    ...chart.querySelectorAll(`.bar-chart__bar--${direction}`),
  ];

  it('la leyenda de sentido resalta una serie y atenúa la otra; al repetir, se quita', async () => {
    const chart = await renderStats();
    const south = screen.getByRole('button', { name: 'Atlántico → Pacífico' });
    expect(south).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(south);

    expect(south).toHaveAttribute('aria-pressed', 'true');
    expect(bars(chart, 'northbound').every((bar) => bar.classList.contains('is-dimmed'))).toBe(
      true,
    );
    expect(bars(chart, 'southbound').some((bar) => bar.classList.contains('is-dimmed'))).toBe(
      false,
    );

    await userEvent.click(south);

    expect(south).toHaveAttribute('aria-pressed', 'false');
    expect(chart.querySelectorAll('.is-dimmed')).toHaveLength(0);
  });

  it('solo un sentido resaltado a la vez', async () => {
    await renderStats();
    const south = screen.getByRole('button', { name: 'Atlántico → Pacífico' });
    const north = screen.getByRole('button', { name: 'Pacífico → Atlántico' });

    await userEvent.click(south);
    await userEvent.click(north);

    expect(south).toHaveAttribute('aria-pressed', 'false');
    expect(north).toHaveAttribute('aria-pressed', 'true');
  });

  it('un tipo filtra la gráfica y conserva la escala de todos los tránsitos', async () => {
    const chart = await renderStats({ daily: skewed });
    // 12 + 1 = 13 tránsitos; el pico diario es 12, así que el eje llega a 15.
    expect(chart).toHaveAccessibleName(/13 en 30 días/);
    expect(within(chart).getByText('15')).toBeInTheDocument();

    const cargo = screen.getByRole('button', { name: /Carga/ });
    await userEvent.click(cargo);

    expect(cargo).toHaveAttribute('aria-pressed', 'true');
    const filtered = screen.getByRole('img', { name: /Tránsitos/ });
    expect(filtered).toHaveAccessibleName(/de tipo Carga.*: 1 en 30 días/);
    // Con 1 solo tránsito el eje sería 4 si se reescalara; sigue en 15.
    expect(within(filtered).getByText('15')).toBeInTheDocument();
    // El <title> de cada barra también dice qué se cuenta.
    const titles = Array.from(filtered.querySelectorAll('g > title'), (t) => t.textContent);
    expect(titles.every((text) => text.includes('tránsitos de tipo Carga'))).toBe(true);
    expect(screen.getByRole('button', { name: /Tanquero/ })).toHaveClass('is-dimmed');
  });

  it('"Quitar filtros" aparece solo con algo activo y lo quita todo', async () => {
    await renderStats({ daily: skewed });
    expect(screen.queryByRole('button', { name: 'Quitar filtros' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Carga/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Atlántico → Pacífico' }));
    await userEvent.click(screen.getByRole('button', { name: 'Quitar filtros' }));

    expect(screen.getByRole('button', { name: /Carga/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Atlántico → Pacífico' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.queryByRole('button', { name: 'Quitar filtros' })).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Tránsitos/ })).toHaveAccessibleName(/13 en 30 días/);
  });

  it('Escape quita los filtros cuando el foco está dentro de la tarjeta', async () => {
    await renderStats({ daily: skewed });
    const cargo = screen.getByRole('button', { name: /Carga/ });
    await userEvent.click(cargo);
    expect(cargo).toHaveFocus();

    await userEvent.keyboard('{Escape}');

    expect(cargo).toHaveAttribute('aria-pressed', 'false');
  });

  it('se maneja con el teclado: Tab hasta el botón y Espacio para activarlo', async () => {
    await renderStats();
    const south = screen.getByRole('button', { name: 'Atlántico → Pacífico' });
    south.focus();

    await userEvent.keyboard(' ');

    expect(south).toHaveAttribute('aria-pressed', 'true');
  });

  it('si al cambiar de periodo el tipo elegido desaparece, el filtro se quita solo', async () => {
    let calls = 0;
    const fetchMock = vi.fn<(url: string) => Promise<Response>>((url) => {
      if (url.includes('/stats/daily')) {
        calls += 1;
        // Primera petición (30 días): hay carga. Segunda (7 días): solo tanqueros.
        return Promise.resolve(
          Response.json(
            calls === 1
              ? skewed
              : { ...skewed, items: [item('2026-11-05', 'southbound', 4, 'tanker')] },
          ),
        );
      }
      if (url.includes('/stats/transit-durations')) {
        return Promise.resolve(Response.json(durations));
      }
      return Promise.resolve(Response.json(waiting));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithQuery(<StatsView token="abc" onUnauthorized={vi.fn()} now={() => NOW} />);
    await userEvent.click(await screen.findByRole('button', { name: /Carga/ }));

    await userEvent.click(screen.getByRole('button', { name: '7 días' }));

    const chart = await screen.findByRole('img', { name: /4 en 7 días/ });
    expect(chart).not.toHaveAccessibleName(/de tipo/);
    expect(screen.queryByRole('button', { name: 'Quitar filtros' })).not.toBeInTheDocument();
  });
});
