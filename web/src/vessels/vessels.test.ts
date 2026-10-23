import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { LiveVessel } from '../live/protocol';
import { fetchVesselTrack, parseVesselDetail, parseVesselTrack } from './api';
import {
  agoText,
  courseText,
  dimensionsText,
  navStatusText,
  shipTypeText,
  speedText,
} from './format';
import { trailFeature } from './trail';

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

describe('formatos de la ficha', () => {
  it('muestra cada dato o un guion si falta', () => {
    expect(shipTypeText(70)).toBe('Carga (70)');
    expect(shipTypeText(null)).toBe('Sin tipo');
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
