import { useEffect, useRef, useState } from 'react';
import { config } from '../config';
import { authMessage, type Bbox, parseServerMessage, subscribeMessage } from './protocol';
import { applyServerMessage, EMPTY_STATE, type VesselState } from './vesselStore';

export type LiveStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed';

export interface LiveVessels {
  vessels: VesselState;
  status: LiveStatus;
  /** Código del último cierre del WebSocket (p. ej. `4401`); null mientras esté en vivo. */
  closeCode: number | null;
}

/** Códigos de cierre de `/ws/live` con trato propio (docs/API_DESIGN.md). */
export const CLOSE_INVALID = 4400;
export const CLOSE_UNAUTHORIZED = 4401;
export const CLOSE_TOO_MANY = 4429;

const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
/** Con `4429` el cupo tarda en liberarse (latido de 30 s, caducidad de 90 s): no insistir antes. */
const TOO_MANY_MIN_DELAY_MS = 15_000;

/**
 * Espera antes del reintento número `attempt` (desde 0): backoff exponencial de 1 s a 30 s con
 * "equal jitter" (entre la mitad y el total del tramo), para que los clientes que cayeron a la
 * vez no vuelvan todos en el mismo segundo.
 */
export function reconnectDelay(
  attempt: number,
  closeCode: number,
  random: () => number = Math.random,
): number {
  const ceiling = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  const delay = ceiling / 2 + (random() * ceiling) / 2;
  return closeCode === CLOSE_TOO_MANY ? Math.max(delay, TOO_MANY_MIN_DELAY_MS) : delay;
}

/** URL de `/ws/live`: la misma origen que la página si `VITE_API_URL` está vacío. */
export function liveSocketUrl(
  apiUrl: string,
  location: Pick<Location, 'protocol' | 'host'>,
): string {
  if (!apiUrl) {
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${location.host}/ws/live`;
  }
  const url = new URL('/ws/live', apiUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

const INITIAL: LiveVessels = { vessels: EMPTY_STATE, status: 'connecting', closeCode: null };

/**
 * Buques en vivo del viewport `bbox`. Con sesión abre `/ws/live`, se autentica en el primer
 * mensaje (el token nunca va en la URL) y se suscribe al viewport; cada `bbox` nuevo es otra
 * suscripción, que el servidor contesta con un snapshot.
 *
 * Si la conexión se cae, reconecta con backoff (y en cuanto vuelve la red) y se suscribe otra vez;
 * los buques se quedan pintados hasta el snapshot nuevo. Un token renovado no reabre la conexión:
 * el servidor solo lo mira en el `auth`, así que se usa en la siguiente. Con `4401` avisa con
 * `onUnauthorized` y espera a recibir otro token; con `4400` (error nuestro) no reintenta.
 */
export function useLiveVessels(
  token: string | null,
  bbox: Bbox | null,
  onUnauthorized?: (rejectedToken: string) => void,
): LiveVessels {
  const active = token !== null;
  const [state, setState] = useState<LiveVessels>(INITIAL);
  // Al cerrar o abrir sesión, lo de la sesión anterior deja de valer (ajuste durante el render).
  const [wasActive, setWasActive] = useState(active);
  if (wasActive !== active) {
    setWasActive(active);
    setState(INITIAL);
  }

  const socketRef = useRef<WebSocket | null>(null);
  // Los valores más recientes, para la conexión que se abra después.
  const bboxRef = useRef(bbox);
  const tokenRef = useRef(token);
  const onUnauthorizedRef = useRef(onUnauthorized);
  // Lo llama el efecto del token: reconecta si la conexión esperaba un token nuevo tras un 4401.
  const tokenChangedRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    onUnauthorizedRef.current = onUnauthorized;
  }, [onUnauthorized]);

  useEffect(() => {
    tokenRef.current = token;
    tokenChangedRef.current?.();
  }, [token]);

  useEffect(() => {
    if (!active) {
      return;
    }
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    // Token que el servidor rechazó; mientras siga siendo el actual, no se reintenta.
    let rejectedToken: string | null = null;

    const connect = () => {
      timer = undefined;
      const currentToken = tokenRef.current;
      if (currentToken === null) {
        return;
      }
      const current = new WebSocket(liveSocketUrl(config.apiUrl, window.location));
      socket = current;
      socketRef.current = current;

      current.addEventListener('open', () => {
        if (socket !== current) {
          return;
        }
        attempt = 0;
        current.send(authMessage(currentToken));
        if (bboxRef.current) {
          current.send(subscribeMessage(bboxRef.current));
        }
        setState((previous) => ({ ...previous, status: 'live', closeCode: null }));
      });
      current.addEventListener('message', (event: MessageEvent<unknown>) => {
        const message = parseServerMessage(event.data);
        if (message && socket === current) {
          setState((previous) => ({
            ...previous,
            vessels: applyServerMessage(previous.vessels, message),
          }));
        }
      });
      current.addEventListener('close', (event) => {
        if (socket !== current) {
          return;
        }
        socket = null;
        socketRef.current = null;
        const { code } = event;
        if (code === CLOSE_INVALID) {
          setState((previous) => ({ ...previous, status: 'closed', closeCode: code }));
          return;
        }
        setState((previous) => ({ ...previous, status: 'reconnecting', closeCode: code }));
        if (code === CLOSE_UNAUTHORIZED) {
          rejectedToken = currentToken;
          onUnauthorizedRef.current?.(currentToken);
          return;
        }
        timer = setTimeout(connect, reconnectDelay(attempt, code));
        attempt += 1;
      });
    };

    tokenChangedRef.current = () => {
      if (rejectedToken !== null && tokenRef.current !== rejectedToken) {
        rejectedToken = null;
        connect();
      }
    };
    // Al volver la red no tiene sentido esperar al siguiente tramo del backoff.
    const handleOnline = () => {
      if (timer !== undefined) {
        clearTimeout(timer);
        connect();
      }
    };
    window.addEventListener('online', handleOnline);
    connect();

    return () => {
      window.removeEventListener('online', handleOnline);
      clearTimeout(timer);
      tokenChangedRef.current = null;
      const open = socket;
      socket = null;
      socketRef.current = null;
      open?.close(1000);
    };
  }, [active]);

  useEffect(() => {
    bboxRef.current = bbox;
    const socket = socketRef.current;
    if (bbox && socket?.readyState === WebSocket.OPEN) {
      socket.send(subscribeMessage(bbox));
    }
  }, [bbox]);

  if (!active) {
    return { vessels: EMPTY_STATE, status: 'idle', closeCode: null };
  }
  return state;
}
