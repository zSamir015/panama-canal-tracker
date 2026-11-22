import { afterEach, describe, expect, it } from 'vitest';
import { readUrlState, writeUrlState } from './urlState';

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('urlState', () => {
  it('lee view=stats y mmsi válido desde los parámetros de la URL', () => {
    expect(readUrlState('?view=stats&mmsi=352001234')).toEqual({
      view: 'stats',
      mmsi: 352001234,
    });
  });

  it('lee y escribe la vista del historial', () => {
    expect(readUrlState('?view=history')).toEqual({ view: 'history', mmsi: null });

    writeUrlState({ view: 'history', mmsi: null });
    expect(window.location.search).toBe('?view=history');
  });

  it('descarta MMSIs inválidos o vistas desconocidas sin romper', () => {
    expect(readUrlState('?view=other&mmsi=123')).toEqual({ view: 'map', mmsi: null });
    expect(readUrlState('?mmsi=abc')).toEqual({ view: 'map', mmsi: null });
    expect(readUrlState('')).toEqual({ view: 'map', mmsi: null });
  });

  it('sincroniza la URL manteniendo el estado limpio cuando vuelve a map sin buque', () => {
    writeUrlState({ view: 'stats', mmsi: 352001234 });
    expect(window.location.search).toBe('?view=stats&mmsi=352001234');

    writeUrlState({ view: 'map', mmsi: null });
    expect(window.location.search).toBe('');
  });
});
