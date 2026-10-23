import { useEffect, useRef, useState } from 'react';
import { config } from '../config';
import { authMessage, type Bbox, parseServerMessage, subscribeMessage } from './protocol';
import { applyServerMessage, EMPTY_STATE, type VesselState } from './vesselStore';

export type LiveStatus = 'idle' | 'connecting' | 'live' | 'closed';

export interface LiveVessels {
  vessels: VesselState;
  status: LiveStatus;
  /** Código de cierre del WebSocket (p. ej. `4401` si el token no vale); null mientras siga abierto. */
  closeCode: number | null;
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

/**
 * Buques en vivo del viewport `bbox`. Con `token` abre `/ws/live`, se autentica en el primer
 * mensaje (el token nunca va en la URL) y se suscribe al viewport; cada `bbox` nuevo es otra
 * suscripción, que el servidor contesta con un snapshot. Sin reconexión todavía (tarea 4.5).
 */
export function useLiveVessels(token: string | null, bbox: Bbox | null): LiveVessels {
  // Cada estado recuerda de qué token es: con un token nuevo, lo anterior deja de valer sin
  // tener que vaciarlo dentro del efecto.
  const [state, setState] = useState<LiveVessels & { token: string | null }>({
    token: null,
    vessels: EMPTY_STATE,
    status: 'idle',
    closeCode: null,
  });
  const socketRef = useRef<WebSocket | null>(null);
  // El viewport más reciente, para suscribirse en cuanto la conexión esté lista.
  const bboxRef = useRef(bbox);

  useEffect(() => {
    if (!token) {
      return;
    }
    const socket = new WebSocket(liveSocketUrl(config.apiUrl, window.location));
    socketRef.current = socket;
    // Los eventos de un socket ya sustituido (token nuevo o desmontaje) se ignoran.
    const isCurrent = () => socketRef.current === socket;

    socket.addEventListener('open', () => {
      if (!isCurrent()) {
        return;
      }
      socket.send(authMessage(token));
      if (bboxRef.current) {
        socket.send(subscribeMessage(bboxRef.current));
      }
      setState({ token, vessels: EMPTY_STATE, status: 'live', closeCode: null });
    });
    socket.addEventListener('message', (event: MessageEvent<unknown>) => {
      const message = parseServerMessage(event.data);
      if (message && isCurrent()) {
        setState((current) => ({
          ...current,
          vessels: applyServerMessage(current.vessels, message),
        }));
      }
    });
    socket.addEventListener('close', (event) => {
      if (!isCurrent()) {
        return;
      }
      setState((current) => ({ ...current, token, status: 'closed', closeCode: event.code }));
    });

    return () => {
      socketRef.current = null;
      socket.close(1000);
    };
  }, [token]);

  useEffect(() => {
    bboxRef.current = bbox;
    const socket = socketRef.current;
    if (bbox && socket?.readyState === WebSocket.OPEN) {
      socket.send(subscribeMessage(bbox));
    }
  }, [bbox]);

  if (!token) {
    return { vessels: EMPTY_STATE, status: 'idle', closeCode: null };
  }
  if (state.token !== token) {
    return { vessels: EMPTY_STATE, status: 'connecting', closeCode: null };
  }
  return { vessels: state.vessels, status: state.status, closeCode: state.closeCode };
}
