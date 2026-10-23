import type { LiveVessel, ServerMessage } from './protocol';

/** Buques pintados en el mapa, por MMSI. Se trata como inmutable: cada cambio crea otro mapa. */
export type VesselState = ReadonlyMap<number, LiveVessel>;

export const EMPTY_STATE: VesselState = new Map();

/**
 * Aplica un mensaje del servidor: el `snapshot` sustituye todo, `update` reemplaza la posición de
 * cada buque y `remove` quita los que salieron del viewport.
 */
export function applyServerMessage(state: VesselState, message: ServerMessage): VesselState {
  switch (message.type) {
    case 'snapshot':
      return new Map(message.vessels.map((vessel) => [vessel.mmsi, vessel]));
    case 'update': {
      if (message.vessels.length === 0) {
        return state;
      }
      const next = new Map(state);
      for (const vessel of message.vessels) {
        next.set(vessel.mmsi, vessel);
      }
      return next;
    }
    case 'remove': {
      if (!message.mmsi.some((mmsi) => state.has(mmsi))) {
        return state;
      }
      const next = new Map(state);
      for (const mmsi of message.mmsi) {
        next.delete(mmsi);
      }
      return next;
    }
  }
}
