import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseTokenResponse, refreshSession, SessionError } from './session';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseTokenResponse', () => {
  it('calcula la caducidad a partir de expires_in', () => {
    expect(parseTokenResponse({ access_token: 'abc', expires_in: 900 }, 1_000)).toEqual({
      accessToken: 'abc',
      expiresAt: 901_000,
    });
  });

  it('sin expires_in válido asume 15 minutos', () => {
    expect(parseTokenResponse({ access_token: 'abc', expires_in: -1 }, 0)?.expiresAt).toBe(900_000);
  });

  it.each([null, 'abc', {}, { access_token: '' }, { access_token: 42 }])('rechaza %j', (body) => {
    expect(parseTokenResponse(body)).toBeNull();
  });
});

describe('refreshSession', () => {
  it('usa la cookie (sin token en el body) y devuelve la sesión nueva', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(200, { access_token: 'nuevo', expires_in: 900 })),
    );

    await expect(refreshSession(fetchImpl)).resolves.toMatchObject({ accessToken: 'nuevo' });

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/auth/refresh');
    expect(init).toEqual({ method: 'POST', credentials: 'include' });
  });

  it('devuelve null si no hay sesión que renovar (401)', async () => {
    await expect(refreshSession(() => Promise.resolve(jsonResponse(401, {})))).resolves.toBeNull();
  });

  it.each([
    ['la red falla', () => Promise.reject(new TypeError('offline'))],
    ['hay límite (429)', () => Promise.resolve(jsonResponse(429, {}))],
    ['Redis no responde (503)', () => Promise.resolve(jsonResponse(503, {}))],
    ['la respuesta no trae token', () => Promise.resolve(jsonResponse(200, {}))],
  ])('lanza SessionError si %s', async (_case, fetchImpl: () => Promise<Response>) => {
    await expect(refreshSession(fetchImpl)).rejects.toThrow(SessionError);
  });

  it('las llamadas en paralelo comparten una sola petición (la cookie rota en cada uso)', async () => {
    let resolve: (response: Response) => void = () => undefined;
    const fetchImpl = vi.fn<typeof fetch>(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );

    const first = refreshSession(fetchImpl);
    const second = refreshSession(fetchImpl);
    // El Web Lock (si existe) es asíncrono: dejar que la petición llegue a salir.
    await vi.waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledOnce();
    });
    resolve(jsonResponse(200, { access_token: 'nuevo', expires_in: 900 }));

    expect(await first).toEqual(await second);
    expect(fetchImpl).toHaveBeenCalledOnce();

    // Terminada, la siguiente renovación es una petición nueva.
    fetchImpl.mockResolvedValueOnce(jsonResponse(200, { access_token: 'otro', expires_in: 900 }));
    await expect(refreshSession(fetchImpl)).resolves.toMatchObject({ accessToken: 'otro' });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('entre pestañas, pone la renovación en fila con un Web Lock', async () => {
    const request = vi.fn((_name: string, task: () => Promise<unknown>) => task());
    vi.stubGlobal('navigator', { locks: { request } });

    await refreshSession(() =>
      Promise.resolve(jsonResponse(200, { access_token: 'nuevo', expires_in: 900 })),
    );

    expect(request).toHaveBeenCalledWith('pct-auth-refresh', expect.any(Function));
  });
});
