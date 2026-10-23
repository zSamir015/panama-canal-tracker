import { describe, expect, it } from 'vitest';
import { authMessage, parseServerMessage, subscribeMessage } from './protocol';
import { applyServerMessage, EMPTY_STATE } from './vesselStore';

const vessel = {
  mmsi: 352001234,
  lon: -79.91,
  lat: 9.35,
  cog: 145.2,
  sog: 7.8,
  ship_type: 70,
  name: 'EXAMPLE',
  ts: '2026-10-16T14:30:00Z',
};

describe('parseServerMessage', () => {
  it('acepta snapshot, update y remove', () => {
    expect(parseServerMessage(JSON.stringify({ type: 'snapshot', vessels: [vessel] }))).toEqual({
      type: 'snapshot',
      vessels: [vessel],
    });
    expect(parseServerMessage(JSON.stringify({ type: 'update', vessels: [] }))).toEqual({
      type: 'update',
      vessels: [],
    });
    expect(parseServerMessage(JSON.stringify({ type: 'remove', mmsi: [352001234] }))).toEqual({
      type: 'remove',
      mmsi: [352001234],
    });
  });

  it('descarta los buques con otra forma y deja los válidos', () => {
    const message = parseServerMessage(
      JSON.stringify({
        type: 'update',
        vessels: [vessel, { ...vessel, lat: 'x' }, { ...vessel, mmsi: 1.5 }, null],
      }),
    );

    expect(message).toEqual({ type: 'update', vessels: [vessel] });
  });

  it.each([
    ['binario', new ArrayBuffer(4)],
    ['JSON roto', '{'],
    ['tipo desconocido', '{"type":"hello"}'],
    ['sin lista', '{"type":"snapshot","vessels":{}}'],
    ['un array', '[]'],
  ])('ignora %s', (_label, raw) => {
    expect(parseServerMessage(raw)).toBeNull();
  });
});

describe('mensajes del cliente', () => {
  it('siguen el contrato de API_DESIGN', () => {
    expect(JSON.parse(authMessage('abc'))).toEqual({ type: 'auth', token: 'abc' });
    expect(JSON.parse(subscribeMessage([-80.2, 8.4, -79.2, 9.7]))).toEqual({
      type: 'subscribe',
      bbox: [-80.2, 8.4, -79.2, 9.7],
    });
  });
});

describe('applyServerMessage', () => {
  const other = { ...vessel, mmsi: 352009999 };

  it('el snapshot sustituye todo lo anterior', () => {
    const before = applyServerMessage(EMPTY_STATE, { type: 'snapshot', vessels: [vessel] });
    const after = applyServerMessage(before, { type: 'snapshot', vessels: [other] });

    expect([...after.keys()]).toEqual([other.mmsi]);
  });

  it('update reemplaza la posición y añade buques nuevos', () => {
    const before = applyServerMessage(EMPTY_STATE, { type: 'snapshot', vessels: [vessel] });
    const moved = { ...vessel, lon: -79.8 };
    const after = applyServerMessage(before, { type: 'update', vessels: [moved, other] });

    expect(after.get(vessel.mmsi)).toEqual(moved);
    expect(after.size).toBe(2);
    expect(before.get(vessel.mmsi)).toEqual(vessel);
  });

  it('remove quita los buques y conserva el estado si no cambia nada', () => {
    const before = applyServerMessage(EMPTY_STATE, { type: 'snapshot', vessels: [vessel, other] });

    expect([...applyServerMessage(before, { type: 'remove', mmsi: [vessel.mmsi] }).keys()]).toEqual(
      [other.mmsi],
    );
    expect(applyServerMessage(before, { type: 'remove', mmsi: [123456789] })).toBe(before);
    expect(applyServerMessage(before, { type: 'update', vessels: [] })).toBe(before);
  });
});
