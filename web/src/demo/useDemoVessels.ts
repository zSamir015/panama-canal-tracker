import { useEffect, useRef, useState } from 'react';
import type { ServerMessage } from '../live/protocol';
import type { LiveStatus } from '../live/useLiveVessels';
import { applyServerMessage, EMPTY_STATE, type VesselState } from '../live/vesselStore';
import recording from './recording.json';

/** Intervalo entre frames de la grabación (1 Hz, como el batching real de `/ws/live`). */
const FRAME_INTERVAL_MS = 1_000;

const frames = recording as unknown as ServerMessage[];

/** Aplica el snapshot inicial de forma segura. */
function initialState(): VesselState {
  const first = frames[0];
  return first === undefined ? EMPTY_STATE : applyServerMessage(EMPTY_STATE, first);
}

export interface DemoVessels {
  vessels: VesselState;
  status: LiveStatus;
  closeCode: null;
}

/**
 * Reproduce la grabación del simulador en bucle. Imita la interfaz de `useLiveVessels` para que
 * `App.tsx` pueda usar uno u otro sin cambiar el mapa.
 */
export function useDemoVessels(): DemoVessels {
  const [state, setState] = useState<VesselState>(initialState);
  const frameRef = useRef(1);

  useEffect(() => {
    if (frames.length === 0) {
      return;
    }

    const timer = setInterval(() => {
      const idx = frameRef.current % frames.length;
      const frame = frames[idx];
      if (frame !== undefined) {
        setState((prev: VesselState) => applyServerMessage(prev, frame));
      }
      frameRef.current = idx + 1;
    }, FRAME_INTERVAL_MS);

    return () => {
      clearInterval(timer);
    };
  }, []);

  return { vessels: state, status: 'live', closeCode: null };
}
