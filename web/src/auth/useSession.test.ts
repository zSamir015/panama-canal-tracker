import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SessionError, type Session } from './session';
import { RENEW_BEFORE_EXPIRY_MS, RENEW_RETRY_MS, useSession } from './useSession';

const MINUTES = 60_000;

function session(accessToken: string, ttl = 15 * MINUTES): Session {
  return { accessToken, expiresAt: Date.now() + ttl };
}

/** Deja correr los temporizadores y las promesas que estos resuelven. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useSession', () => {
  it('al cargar recupera la sesión con la cookie del refresh', async () => {
    const refresh = vi.fn(() => Promise.resolve(session('recuperado')));
    const { result } = renderHook(() => useSession(refresh));

    expect(result.current.status).toBe('restoring');
    await advance(0);

    expect(result.current).toMatchObject({ status: 'signedIn', token: 'recuperado' });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it.each([
    ['no hay cookie (401)', () => Promise.resolve(null)],
    ['la API no responde', () => Promise.reject(new SessionError('x'))],
  ])('sin sesión que recuperar (%s) pide entrar, sin aviso de caducidad', async (_c, refresh) => {
    const { result } = renderHook(() => useSession(refresh));
    await advance(0);

    expect(result.current).toMatchObject({ status: 'signedOut', token: null, expired: false });
  });

  it('renueva el token un minuto antes de que caduque', async () => {
    const refresh = vi
      .fn<() => Promise<Session | null>>()
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(session('renovado'));
    const { result } = renderHook(() => useSession(refresh));
    await advance(0);

    act(() => {
      result.current.signIn(session('login'));
    });
    expect(result.current.token).toBe('login');

    await advance(15 * MINUTES - RENEW_BEFORE_EXPIRY_MS - 1);
    expect(result.current.token).toBe('login');
    await advance(1);

    expect(result.current.token).toBe('renovado');
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('si la renovación falla por red conserva el token y reintenta', async () => {
    const refresh = vi
      .fn<() => Promise<Session | null>>()
      .mockResolvedValueOnce(session('inicial', 2 * MINUTES))
      .mockRejectedValueOnce(new SessionError('offline'))
      .mockResolvedValueOnce(session('renovado'));
    const { result } = renderHook(() => useSession(refresh));
    await advance(0);

    await advance(MINUTES);
    expect(result.current).toMatchObject({ status: 'signedIn', token: 'inicial' });

    await advance(RENEW_RETRY_MS);
    expect(result.current.token).toBe('renovado');
  });

  it('un token rechazado se renueva al momento; uno que ya no es el actual, no', async () => {
    const refresh = vi
      .fn<() => Promise<Session | null>>()
      .mockResolvedValueOnce(session('viejo'))
      .mockResolvedValueOnce(session('nuevo'));
    const { result } = renderHook(() => useSession(refresh));
    await advance(0);

    act(() => {
      result.current.renew('otro-token');
    });
    await advance(0);
    expect(refresh).toHaveBeenCalledOnce();

    act(() => {
      result.current.renew('viejo');
    });
    await advance(0);
    expect(result.current.token).toBe('nuevo');
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('si la API dice que ya no hay sesión, vuelve al login avisando que caducó', async () => {
    const refresh = vi
      .fn<() => Promise<Session | null>>()
      .mockResolvedValueOnce(session('viejo'))
      .mockResolvedValueOnce(null);
    const { result } = renderHook(() => useSession(refresh));
    await advance(0);

    act(() => {
      result.current.renew('viejo');
    });
    await advance(0);

    expect(result.current).toMatchObject({ status: 'signedOut', token: null, expired: true });
  });
});
