import { describe, expect, it } from 'vitest';
import { boundsToBbox, focusOffset } from './viewport';

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

describe('focusOffset', () => {
  // Mapa de 390 × 700 px con una hoja que tapa el 45 % de abajo: se ve hasta y = 385.
  const map = { width: 390, height: 700 };
  const sheet = 0.45;
  const at = (x: number, y: number) => focusOffset({ x, y }, map, sheet);

  it('no mueve el mapa si el buque ya se ve encima de la hoja', () => {
    expect(at(195, 200)).toBeNull();
    expect(at(48, 48)).toBeNull();
    expect(at(390 - 48, 385 - 48)).toBeNull();
  });

  it('lo lleva al centro de la parte visible si queda bajo la hoja o pegado a un borde', () => {
    // Centrar con un desplazamiento de -157,5 px deja el buque en y = 192,5: el centro de 0..385.
    expect(at(195, 600)).toBe(-157.5);
    expect(at(195, 385 - 47)).toBe(-157.5);
    expect(at(195, 10)).toBe(-157.5);
    expect(at(195, -30)).toBe(-157.5);
  });

  it('también si está fuera por un lado (elegido desde la lista de tránsitos)', () => {
    expect(at(-200, 200)).toBe(-157.5);
    expect(at(390 - 47, 200)).toBe(-157.5);
  });
});
