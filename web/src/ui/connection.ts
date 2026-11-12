import type { LiveStatus } from '../live/useLiveVessels';

export type ConnectionTone = 'ok' | 'pending' | 'down';

/** Verde si llegan datos, ámbar mientras se (re)conecta y rojo si no hay conexión. */
export function connectionTone(status: LiveStatus): ConnectionTone {
  switch (status) {
    case 'live':
      return 'ok';
    case 'connecting':
    case 'reconnecting':
      return 'pending';
    case 'idle':
    case 'closed':
      return 'down';
  }
}
