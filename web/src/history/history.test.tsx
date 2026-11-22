import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWithQuery } from '../test/render';
import { HistoryView } from './HistoryView';
import { HISTORY_PERIODS, matchesFilter, MAX_ROWS, seenText } from './periods';

const NOW = Date.parse('2026-11-21T12:00:00Z');

const row = (mmsi: number, overrides: Record<string, unknown> = {}) => ({
  mmsi,
  name: `BUQUE ${String(mmsi)}`,
  imo: null,
  ship_type: 70,
  last_seen_at: '2026-11-21T11:30:00Z',
  ...overrides,
});

function stubVessels(items: unknown[], status = 200) {
  const fetchMock = vi.fn<typeof fetch>(() =>
    Promise.resolve(
      Response.json(status === 200 ? { items, total: items.length, page: 1, size: 200 } : {}, {
        status,
      }),
    ),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function urlOf(input: RequestInfo | URL | undefined): URL {
  const text =
    typeof input === 'string' ? input : input instanceof URL ? input.href : (input?.url ?? '');
  return new URL(text, 'http://localhost');
}

function renderHistory(props: Partial<Parameters<typeof HistoryView>[0]> = {}) {
  const onOpen = vi.fn();
  const onUnauthorized = vi.fn();
  const { container } = renderWithQuery(
    <HistoryView
      token="abc"
      onUnauthorized={onUnauthorized}
      onOpen={onOpen}
      now={() => NOW}
      {...props}
    />,
  );
  return { onOpen, onUnauthorized, container };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('seenText', () => {
  it('cuenta en minutos, horas y, desde 48 h, en días', () => {
    const ago = (ms: number) => new Date(NOW - ms).toISOString();
    expect(seenText(ago(5 * 60_000), NOW)).toBe('hace 5 min');
    expect(seenText(ago(3 * 3_600_000), NOW)).toBe('hace 3 h');
    expect(seenText(ago(47 * 3_600_000), NOW)).toBe('hace 47 h');
    expect(seenText(ago(4 * 86_400_000), NOW)).toBe('hace 4 d');
    expect(seenText(ago(-60_000), NOW)).toBe('hace 0 min'); // hora futura: no es negativa
    expect(seenText(null, NOW)).toBe('—');
    expect(seenText('ayer', NOW)).toBe('—');
  });
});

describe('matchesFilter', () => {
  const vessel = { mmsi: 352001234, name: 'Pacific Star', imo: 9301234 } as never;

  it('busca por nombre, MMSI o IMO sin distinguir mayúsculas', () => {
    expect(matchesFilter(vessel, '')).toBe(true);
    expect(matchesFilter(vessel, 'pacific')).toBe(true);
    expect(matchesFilter(vessel, '0012')).toBe(true);
    expect(matchesFilter(vessel, '9301')).toBe(true);
    expect(matchesFilter(vessel, 'atlantic')).toBe(false);
  });

  it('un buque sin nombre ni IMO solo coincide por MMSI', () => {
    const bare = { mmsi: 352001234, name: null, imo: null } as never;
    expect(matchesFilter(bare, '3520')).toBe(true);
    expect(matchesFilter(bare, 'star')).toBe(false);
  });
});

describe('HISTORY_PERIODS', () => {
  it('la estela de cada periodo nunca es más larga que el periodo ni que 7 días', () => {
    const trailMs = { '24h': 24, '48h': 48, '7d': 168 } as const;
    for (const period of HISTORY_PERIODS) {
      const hours = trailMs[period.trail as keyof typeof trailMs];
      expect(hours * 3_600_000).toBeLessThanOrEqual(Math.max(period.ms, 7 * 86_400_000));
      expect(hours).toBeLessThanOrEqual(168);
    }
  });
});

describe('HistoryView', () => {
  it('lista los buques vistos con su tipo, nombre y cuánto hace', async () => {
    stubVessels([
      row(352000001),
      row(352000002, { name: null, last_seen_at: '2026-11-18T12:00:00Z' }),
    ]);
    renderHistory();

    expect(await screen.findByText('BUQUE 352000001')).toBeVisible();
    expect(screen.getByText('hace 30 min')).toBeVisible();
    expect(screen.getByText('MMSI 352000002')).toBeVisible(); // sin nombre: el MMSI
    expect(screen.getByText('hace 3 d')).toBeVisible();
    expect(screen.getByText(/2 de 2 buques vistos en las últimas 24 horas/)).toBeVisible();
  });

  it('pide a la API solo los vistos desde hace el periodo, en UTC', async () => {
    const fetchMock = stubVessels([]);
    renderHistory();
    await screen.findByText(/No hay buques con posiciones en las últimas 24 horas/);

    const [first] = fetchMock.mock.calls[0] ?? [];
    const asked = urlOf(first);
    expect(asked.pathname).toBe('/api/v1/vessels');
    expect(asked.searchParams.get('seen_since')).toMatch(/Z$/);
    const since = Date.parse(asked.searchParams.get('seen_since') ?? '');
    expect(Date.now() - since).toBeGreaterThanOrEqual(24 * 3_600_000 - 1000);
    expect(Date.now() - since).toBeLessThan(24 * 3_600_000 + 60_000);
  });

  it('al cambiar de periodo vuelve a pedir y abre con la estela de ese periodo', async () => {
    const fetchMock = stubVessels([row(352000001)]);
    const { onOpen } = renderHistory();
    await screen.findByText('BUQUE 352000001');

    const group = screen.getByRole('group', { name: 'Periodo' });
    expect(within(group).getByRole('button', { name: '24 horas' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(within(group).getByRole('button', { name: '48 horas' }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    await screen.findByText(/en las últimas 48 horas/);
    await userEvent.click(screen.getByRole('button', { name: /BUQUE 352000001/ }));
    expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ mmsi: 352000001 }), '48h');

    await userEvent.click(within(group).getByRole('button', { name: '30 días' }));
    await screen.findByText(/en las últimas 30 días/);
    await userEvent.click(screen.getByRole('button', { name: /BUQUE 352000001/ }));
    expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ mmsi: 352000001 }), '7d');
  });

  it('el filtro reduce la lista por nombre, MMSI o IMO', async () => {
    stubVessels([
      row(352000001, { name: 'PACIFIC STAR' }),
      row(352000002, { name: 'ATLANTIC DAWN', imo: 9100007 }),
    ]);
    renderHistory();
    await screen.findByText('PACIFIC STAR');

    await userEvent.type(screen.getByRole('searchbox'), 'atlantic');

    expect(screen.queryByText('PACIFIC STAR')).not.toBeInTheDocument();
    expect(screen.getByText('ATLANTIC DAWN')).toBeVisible();
    expect(screen.getByText(/1 de 2 buques/)).toBeVisible();
  });

  it('muestra como texto un nombre con marcado HTML, nunca como HTML', async () => {
    stubVessels([row(352000001, { name: '<img src=x onerror=alert(1)>' })]);
    const { container } = renderHistory();

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeVisible();
    expect(container.querySelector('img')).toBeNull();
  });

  it('con muchos buques pinta los más recientes y avisa', async () => {
    const many = Array.from({ length: MAX_ROWS + 5 }, (_, index) => row(352000000 + index));
    stubVessels(many);
    renderHistory();

    await screen.findByText(`BUQUE 352000000`);
    expect(screen.getAllByRole('button', { name: /BUQUE/ })).toHaveLength(MAX_ROWS);
    expect(screen.getByText(/usa el filtro para encontrar otro/)).toBeVisible();
  });

  it('enseña el error de la API sin romper', async () => {
    stubVessels([], 500);
    renderHistory();

    expect(await screen.findByRole('alert')).toHaveTextContent(/no respondió bien/);
  });

  it('un 401 avisa para renovar la sesión', async () => {
    stubVessels([], 401);
    const { onUnauthorized } = renderHistory();

    await waitFor(() => {
      expect(onUnauthorized).toHaveBeenCalledWith('abc');
    });
  });
});
