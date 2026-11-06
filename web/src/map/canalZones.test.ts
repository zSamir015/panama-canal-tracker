import type { Polygon } from 'geojson';
import { describe, expect, it } from 'vitest';
import canalZones from './canalZones.json';
import { CANAL_BBOX } from './viewport';

describe('canalZones', () => {
  it('trae las dos zonas de entrada como polígonos', () => {
    const ids = canalZones.features.map((feature) => feature.properties.id);
    expect(ids).toEqual(['atlantic_entrance', 'pacific_entrance']);
    for (const feature of canalZones.features) {
      expect(feature.geometry.type).toBe('Polygon');
    }
  });

  it('tiene los anillos cerrados y en orden [lon, lat] dentro del área del Canal', () => {
    const [minLon, minLat, maxLon, maxLat] = CANAL_BBOX;
    for (const feature of canalZones.features) {
      const [ring] = feature.geometry.coordinates as Polygon['coordinates'];
      expect(ring?.[0]).toEqual(ring?.[ring.length - 1]);
      for (const [lon, lat] of ring ?? []) {
        expect(lon).toBeGreaterThanOrEqual(minLon);
        expect(lon).toBeLessThanOrEqual(maxLon);
        expect(lat).toBeGreaterThanOrEqual(minLat);
        expect(lat).toBeLessThanOrEqual(maxLat);
      }
    }
  });
});
