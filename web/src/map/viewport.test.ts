import { describe, expect, it } from 'vitest';
import { boundsToBbox } from './viewport';

describe('boundsToBbox', () => {
  it('devuelve los límites en orden GeoJSON', () => {
    expect(boundsToBbox(-80.2, 8.4, -79.2, 9.7)).toEqual([-80.2, 8.4, -79.2, 9.7]);
  });

  it('redondea a seis decimales', () => {
    expect(boundsToBbox(-80.12345678, 8.1, -79.1, 9.987654321)).toEqual([
      -80.123457, 8.1, -79.1, 9.987654,
    ]);
  });

  it('pide todas las longitudes si la vista cruza el antimeridiano', () => {
    expect(boundsToBbox(170, -10, 190, 10)).toEqual([-180, -10, 180, 10]);
    expect(boundsToBbox(-200, -10, -170, 10)).toEqual([-180, -10, 180, 10]);
  });

  it('limita las latitudes y la vuelta al mundo completa', () => {
    expect(boundsToBbox(-400, -95, 400, 95)).toEqual([-180, -90, 180, 90]);
  });
});
