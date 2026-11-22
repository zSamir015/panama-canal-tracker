import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { LiveVessel } from '../live/protocol';
import {
  DIRECTORY_MAX_PAGES,
  DIRECTORY_PAGE_SIZE,
  fetchSeenVessels,
  fetchVesselDirectory,
  fetchVesselTrack,
  parseVesselDetail,
  parseVesselTrack,
} from './api';
import {
  agoText,
  courseText,
  dimensionsText,
  navStatusText,
  aisTypeCodeText,
  speedText,
} from './format';
import { trailFeature } from './trail';
import { DEFAULT_TRAIL_WINDOW, TRAIL_WINDOWS, trailWindow } from './trailWindow';

const detail = {
  mmsi: 352001234,
  name: 'EXAMPLE',
  imo: null,
  ship_type: 70,
  length_m: 225.4,
  beam_m: null,
  last_seen_at: '2026-10-23T17:00:00Z',
  last_position: {
    received_at: '2026-10-23T17:00:00Z',
    lat: 9.35,
    lon: -79.91,
    sog: 7.8,
    cog: 145.2,
    heading: null,
    nav_status: 0,
  },
};

const track = {
  type: 'Feature',
  geometry: {
    type: 'LineString',
    coordinates: [
      [-79.7, 9.1],
      [-79.8, 9.2],
    ],
  },
  properties: {
    mmsi: 352001234,
    from: '2026-10-23T16:30:00Z',
    to: '2026-10-23T17:00:00Z',
    timestamps: ['2026-10-23T16:50:00Z', '2026-10-23T16:55:00Z'],
    truncated: false,
  },
};

describe('parseVesselDetail', () => {
  it('acepta la ficha de la API', () => {
    expect(parseVesselDetail(detail)).toEqual(detail);
    expect(parseVesselDetail({ ...detail, last_position: null })).not.toBeNull();
  });

  it.each([
    ['sin MMSI', { ...detail, mmsi: undefined }],
    ['nombre que no es texto', { ...detail, name: 7 }],
    ['posición rota', { ...detail, last_position: { lat: 'x' } }],
    ['un array', []],
  ])('rechaza %s', (_label, body) => {
    expect(parseVesselDetail(body)).toBeNull();
  });
});

describe('parseVesselTrack', () => {
  it('acepta un LineString y una estela sin geometría', () => {
    expect(parseVesselTrack(track)).toEqual({
      coordinates: track.geometry.coordinates,
      timestamps: track.properties.timestamps,
      truncated: false,
    });
    expect(parseVesselTrack({ ...track, geometry: null })?.coordinates).toEqual([]);
  });

  it.each([
    ['otra geometría', { ...track, geometry: { type: 'Point', coordinates: [1, 2] } }],
    ['coordenadas rotas', { ...track, geometry: { type: 'LineString', coordinates: [[1]] } }],
    ['sin propiedades', { ...track, properties: null }],
  ])('rechaza %s', (_label, body) => {
    expect(parseVesselTrack(body)).toBeNull();
  });
});

describe('fetchVesselTrack', () => {
  it('pide la estela con el token en la cabecera, nunca en la URL', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(track)));

    await fetchVesselTrack(352001234, 'abc', fetchImpl);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/vessels/352001234/history');
    expect(init?.headers).toEqual({ Authorization: 'Bearer abc' });
  });

  it.each([
    [401, 'La sesión caducó.'],
    [404, 'No hay datos de este buque.'],
    [500, 'La API no respondió bien. Inténtalo de nuevo.'],
  ])('convierte un %s en ApiError', async (status, message) => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(Response.json({}, { status })));

    const error: unknown = await fetchVesselTrack(352001234, 'abc', fetchImpl).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status, message });
  });

  it('una respuesta con otra forma es un error, no datos a medias', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(Response.json({ type: 'x' })));

    await expect(fetchVesselTrack(352001234, 'abc', fetchImpl)).rejects.toThrow('inesperada');
  });
});

function urlOf(input: RequestInfo | URL | undefined): string {
  if (input === undefined) {
    return '';
  }
  if (typeof input === 'string') {
    return input;
  }
  return input instanceof URL ? input.href : input.url;
}

describe('fetchVesselTrack con ventana', () => {
  it('pide desde hace la ventana con `from` en UTC y sin tocar el resto de la URL', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(track)));
    const before = Date.now();

    await fetchVesselTrack(352001234, 'abc', fetchImpl, 6 * 3_600_000);

    const [url] = fetchImpl.mock.calls[0] ?? [];
    const asked = new URL(urlOf(url), 'http://localhost');
    expect(asked.pathname).toBe('/api/v1/vessels/352001234/history');
    const from = Date.parse(asked.searchParams.get('from') ?? '');
    expect(String(asked.searchParams.get('from'))).toMatch(/Z$/);
    expect(from).toBeGreaterThanOrEqual(before - 6 * 3_600_000);
    expect(from).toBeLessThanOrEqual(Date.now() - 6 * 3_600_000);
    expect([...asked.searchParams.keys()]).toEqual(['from']);
  });

  it('ninguna ventana pasa de los 7 días que admite el servidor', () => {
    for (const item of TRAIL_WINDOWS) {
      expect(item.ms).toBeLessThan(7 * 24 * 3_600_000);
    }
    expect(DEFAULT_TRAIL_WINDOW.ms).toBe(30 * 60_000);
    expect(trailWindow('7d').ms).toBeGreaterThan(trailWindow('24h').ms);
  });

  it('los huecos de señal tolerados crecen con la ventana', () => {
    const gaps = TRAIL_WINDOWS.map((item) => item.gapMs);
    expect(gaps).toEqual([...gaps].sort((x, y) => x - y));
    expect(new Set(gaps).size).toBe(gaps.length);
  });
});

describe('fetchSeenVessels', () => {
  it('pide `seen_since` en UTC y todas las páginas, con el token en la cabecera', async () => {
    const make = (mmsi: number) => ({
      mmsi,
      name: null,
      imo: null,
      ship_type: null,
      last_seen_at: null,
    });
    const fetchImpl = vi.fn<typeof fetch>((input) => {
      const page = new URL(urlOf(input), 'http://localhost').searchParams.get('page');
      const items = page === '1' ? [make(352000001)] : [make(352000002)];
      return Promise.resolve(Response.json({ items, total: 2, page: Number(page), size: 200 }));
    });
    const before = Date.now();

    const all = await fetchSeenVessels('abc', 48 * 3_600_000, fetchImpl);

    expect(all.map((item) => item.mmsi)).toEqual([352000001, 352000002]);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    const asked = new URL(urlOf(url), 'http://localhost');
    const since = asked.searchParams.get('seen_since') ?? '';
    expect(since).toMatch(/Z$/);
    expect(Date.parse(since)).toBeGreaterThanOrEqual(before - 48 * 3_600_000);
    expect(init?.headers).toEqual({ Authorization: 'Bearer abc' });
  });
});

describe('fetchVesselDirectory', () => {
  const row = (mmsi: number) => ({
    mmsi,
    name: null,
    imo: null,
    ship_type: null,
    last_seen_at: null,
  });

  it('pide páginas hasta tener todos los buques', async () => {
    const pages: Record<string, unknown> = {
      '1': { items: [row(352000001), row(352000002)], total: 3, page: 1, size: 200 },
      '2': { items: [row(352000003)], total: 3, page: 2, size: 200 },
    };
    const fetchImpl = vi.fn<typeof fetch>((input) => {
      const page = new URL(urlOf(input), 'http://localhost').searchParams.get('page') ?? '';
      return Promise.resolve(Response.json(pages[page]));
    });

    const all = await fetchVesselDirectory('abc', fetchImpl);

    expect(all.map((item) => item.mmsi)).toEqual([352000001, 352000002, 352000003]);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const [first] = fetchImpl.mock.calls[0] ?? [];
    expect(urlOf(first)).toContain(`size=${String(DIRECTORY_PAGE_SIZE)}&page=1`);
  });

  it('se para en una página vacía aunque el total prometa más', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() =>
      Promise.resolve(Response.json({ items: [], total: 50, page: 1, size: 200 })),
    );

    expect(await fetchVesselDirectory('abc', fetchImpl)).toEqual([]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('no pide más páginas que el tope', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() =>
      Promise.resolve(Response.json({ items: [row(352000001)], total: 99999, page: 1, size: 200 })),
    );

    await fetchVesselDirectory('abc', fetchImpl);

    expect(fetchImpl).toHaveBeenCalledTimes(DIRECTORY_MAX_PAGES);
  });

  it('una respuesta sin total es un error, no una lista a medias', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() =>
      Promise.resolve(Response.json({ items: [row(352000001)] })),
    );

    await expect(fetchVesselDirectory('abc', fetchImpl)).rejects.toThrow('inesperada');
  });
});

describe('formatos de la ficha', () => {
  it('muestra cada dato o un guion si falta', () => {
    expect(aisTypeCodeText(70)).toBe('70');
    expect(aisTypeCodeText(null)).toBe('—');
    expect(navStatusText(1)).toBe('Fondeado');
    expect(navStatusText(14)).toBe('Sin definir (14)');
    expect(navStatusText(null)).toBe('—');
    expect(speedText(7.84)).toBe('7.8 nudos');
    expect(courseText(145.6)).toBe('146°');
    expect(dimensionsText(225.4, null)).toBe('225 m × ?');
    expect(dimensionsText(null, null)).toBe('—');
  });

  it('dice hace cuánto llegó la última señal', () => {
    const now = Date.parse('2026-10-23T17:00:00Z');

    expect(agoText('2026-10-23T16:59:30Z', now)).toBe('hace 30 s');
    expect(agoText('2026-10-23T16:57:00Z', now)).toBe('hace 3 min');
    expect(agoText('2026-10-23T14:00:00Z', now)).toBe('hace 3 h');
    expect(agoText('no es una fecha', now)).toBe('—');
    expect(agoText(null, now)).toBe('—');
  });
});

describe('trailFeature', () => {
  const parsed = {
    coordinates: track.geometry.coordinates as [number, number][],
    timestamps: track.properties.timestamps,
    truncated: false,
  };
  const live: LiveVessel = {
    mmsi: 352001234,
    lon: -79.9,
    lat: 9.3,
    cog: 145,
    sog: 7,
    ship_type: 70,
    name: 'EXAMPLE',
    ts: '2026-10-23T16:58:00Z',
  };

  it('une la estela con la posición en vivo si es más reciente', () => {
    expect(trailFeature(parsed, live)?.geometry.coordinates).toEqual([
      [
        [-79.7, 9.1],
        [-79.8, 9.2],
        [-79.9, 9.3],
      ],
    ]);
    expect(
      trailFeature(parsed, { ...live, ts: '2026-10-23T16:00:00Z' })?.geometry.coordinates,
    ).toEqual([parsed.coordinates]);
  });

  it('corta la estela donde faltan más de 5 minutos de señal', () => {
    const withGap = {
      coordinates: [
        [-79.6, 9.0],
        [-79.65, 9.05],
        [-79.7, 9.1],
        [-79.8, 9.2],
        [-79.85, 9.25],
      ] as [number, number][],
      timestamps: [
        '2026-10-23T16:30:00Z',
        '2026-10-23T16:31:00Z',
        '2026-10-23T16:32:00Z',
        '2026-10-23T16:50:00Z', // 18 min sin señal
        '2026-10-23T16:51:00Z',
      ],
      truncated: false,
    };

    expect(trailFeature(withGap, undefined)?.geometry.coordinates).toEqual([
      withGap.coordinates.slice(0, 3),
      withGap.coordinates.slice(3),
    ]);
  });

  it('con una ventana larga tolera huecos mayores antes de cortar', () => {
    const sparse = {
      coordinates: [
        [-79.6, 9.0],
        [-79.7, 9.1],
        [-79.8, 9.2],
      ] as [number, number][],
      timestamps: ['2026-10-23T10:00:00Z', '2026-10-23T11:10:00Z', '2026-10-23T11:13:00Z'],
      truncated: false,
    };

    // 70 min sin señal al principio: con los 5 min de la ventana corta se parte; con la de 24 h
    // (2 h) no.
    expect(trailFeature(sparse, undefined)?.geometry.coordinates).toEqual([
      sparse.coordinates.slice(1),
    ]);
    expect(trailFeature(sparse, undefined, trailWindow('24h').gapMs)?.geometry.coordinates).toEqual(
      [sparse.coordinates],
    );
  });

  it('descarta los tramos de un solo punto y sin dos puntos no hay línea', () => {
    const lonely = {
      coordinates: [
        [-79.6, 9.0],
        [-79.8, 9.2],
      ] as [number, number][],
      timestamps: ['2026-10-23T16:00:00Z', '2026-10-23T16:50:00Z'],
      truncated: false,
    };

    expect(trailFeature(lonely, undefined)).toBeNull();
    expect(trailFeature(undefined, live)).toBeNull();
    expect(
      trailFeature({ coordinates: [], timestamps: [], truncated: false }, undefined),
    ).toBeNull();
  });
});
