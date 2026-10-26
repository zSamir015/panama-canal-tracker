import { useCallback, useEffect, useRef, useState } from 'react';
import { refreshSession, type Session } from './session';

export type SessionStatus = 'restoring' | 'signedOut' | 'signedIn';

/** Margen con el que se renueva el access token antes de que caduque. */
export const RENEW_BEFORE_EXPIRY_MS = 60_000;
/** Espera entre reintentos si la renovación falla por red o por la API (no por la sesión). */
export const RENEW_RETRY_MS = 10_000;

interface State {
  status: SessionStatus;
  session: Session | null;
  /** La sesión existía y la API dejó de aceptarla: el login lo explica. */
  expired: boolean;
  /** Cuándo toca la próxima renovación (ms desde epoch); null si no hay nada que renovar. */
  renewAt: number | null;
}

export interface SessionApi {
  status: SessionStatus;
  token: string | null;
  expired: boolean;
  /** Tras un login correcto. */
  signIn: (session: Session) => void;
  /**
   * La API rechazó `rejectedToken` (401 o cierre 4401): renovar ya. Si ese token ya no es el
   * actual, otra renovación se adelantó y no hace falta nada.
   */
  renew: (rejectedToken: string) => void;
}

function signedIn(session: Session, now: number): State {
  return {
    status: 'signedIn',
    session,
    expired: false,
    renewAt: Math.max(now, session.expiresAt - RENEW_BEFORE_EXPIRY_MS),
  };
}

function signedOut(expired: boolean): State {
  return { status: 'signedOut', session: null, expired, renewAt: null };
}

/**
 * Sesión del navegador. El access token vive solo en memoria (AGENTS.md §8.4); al cargar la
 * página se recupera con la cookie del refresh, se renueva un minuto antes de caducar y también
 * cuando la API lo rechaza. Si la renovación falla por red, el token actual se conserva y se
 * reintenta; si la API dice que no hay sesión (401), toca volver a entrar.
 */
export function useSession(refresh: () => Promise<Session | null> = refreshSession): SessionApi {
  // Al cargar, lo primero es intentar recuperar la sesión de la cookie.
  const [state, setState] = useState<State>({
    status: 'restoring',
    session: null,
    expired: false,
    renewAt: 0,
  });
  // Una renovación en curso no se descarta aunque cambie `renewAt`: la cookie ya habrá rotado y
  // perder el access token nuevo obligaría a otra renovación. Solo se ignora tras desmontar.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const { renewAt } = state;
  useEffect(() => {
    if (renewAt === null) {
      return;
    }
    const timer = setTimeout(
      () => {
        refresh().then(
          (session) => {
            if (!mountedRef.current) {
              return;
            }
            setState((current) =>
              session ? signedIn(session, Date.now()) : signedOut(current.status === 'signedIn'),
            );
          },
          () => {
            if (!mountedRef.current) {
              return;
            }
            setState((current) =>
              current.status === 'restoring'
                ? signedOut(false)
                : { ...current, renewAt: Date.now() + RENEW_RETRY_MS },
            );
          },
        );
      },
      Math.max(0, renewAt - Date.now()),
    );
    return () => {
      clearTimeout(timer);
    };
  }, [renewAt, refresh]);

  const signIn = useCallback((session: Session) => {
    setState(signedIn(session, Date.now()));
  }, []);

  const renew = useCallback((rejectedToken: string) => {
    setState((current) =>
      current.status === 'signedIn' && current.session?.accessToken === rejectedToken
        ? { ...current, renewAt: Date.now() }
        : current,
    );
  }, []);

  return {
    status: state.status,
    token: state.session?.accessToken ?? null,
    expired: state.expired,
    signIn,
    renew,
  };
}
