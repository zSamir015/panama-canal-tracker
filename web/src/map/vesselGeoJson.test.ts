import { describe, expect, it } from 'vitest';
import type { LiveVessel } from '../live/protocol';
import { shipCategory, toFeatureCollection } from './vesselGeoJson';
import { arrowIcon, CABIN_SIZE, cabinIcon, dotIcon, ICON_SIZE } from './vesselIcons';

const vessel: LiveVessel = {
  mmsi: 352001234,
  lon: -79.91,
  lat: 9.35,
  cog: 145.2,
  sog: 7.8,
  ship_type: 70,
  name: '<img src=x onerror=alert(1)>',
  ts: '2026-10-16T14:30:00Z',
};

describe('shipCategory', () => {
  it.each([
    [70, 'cargo'],
    [79, 'cargo'],
    [80, 'tanker'],
    [60, 'passenger'],
    [52, 'tug'],
    [31, 'tug'],
    [30, 'fishing'],
    [37, 'pleasure'],
    [99, 'other'],
    [null, 'unknown'],
  ] as const)('%s es %s', (shipType, category) => {
    expect(shipCategory(shipType)).toBe(category);
  });
});

describe('toFeatureCollection', () => {
  it('convierte cada buque en un punto con su categoría y rumbo', () => {
    const collection = toFeatureCollection(new Map([[vessel.mmsi, vessel]]));

    expect(collection.features).toEqual([
      {
        type: 'Feature',
        id: vessel.mmsi,
        geometry: { type: 'Point', coordinates: [-79.91, 9.35] },
        properties: { mmsi: vessel.mmsi, category: 'cargo', cog: 145.2, hasCourse: true },
      },
    ]);
  });

  it('marca los buques sin rumbo y no copia el nombre a la capa', () => {
    const [feature] = toFeatureCollection(new Map([[1, { ...vessel, cog: null }]])).features;

    expect(feature?.properties).toEqual({
      mmsi: vessel.mmsi,
      category: 'cargo',
      cog: 0,
      hasCourse: false,
    });
    expect(JSON.stringify(feature)).not.toContain('onerror');
  });
});

describe('iconos SDF', () => {
  function alphaAt(image: ReturnType<typeof arrowIcon>, x: number, y: number): number {
    return image.data[(y * ICON_SIZE + x) * 4 + 3] ?? -1;
  }

  it('la flecha es opaca dentro, transparente lejos y apunta al norte', () => {
    const arrow = arrowIcon();

    expect(arrow.data).toHaveLength(ICON_SIZE * ICON_SIZE * 4);
    expect(alphaAt(arrow, 16, 14)).toBeGreaterThan(191);
    expect(alphaAt(arrow, 0, 31)).toBe(0);
    // La punta (arriba) es más estrecha que la base.
    expect(alphaAt(arrow, 12, 6)).toBeLessThan(alphaAt(arrow, 12, 24));
  });

  it('el punto está centrado', () => {
    const dot = dotIcon();

    expect(alphaAt(dot, 16, 16)).toBeGreaterThan(191);
    expect(alphaAt(dot, 16, 2)).toBeLessThan(191);
  });

  it('el puente del casco tiene textura blanca centrada cerca de popa', () => {
    const cabin = cabinIcon();

    expect(cabin.data).toHaveLength(CABIN_SIZE * CABIN_SIZE * 4);
    const centerBridgeOffset = (45 * CABIN_SIZE + 32) * 4;
    expect(cabin.data[centerBridgeOffset + 3]).toBeGreaterThan(200);
    expect(cabin.data[3]).toBe(0);
  });
});
