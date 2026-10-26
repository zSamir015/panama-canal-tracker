import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Bbox } from './protocol';
import { liveSocketUrl, reconnectDelay, useLiveVessels } from './useLiveVessels';

/** WebSocket de mentira: guarda lo enviado y deja disparar eventos desde el test. */
class FakeWebSocket extends EventTarget {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readyState = 0;
  sent: unknown[] = [];
  closedWith: number | null = null;

  constructor(readonly url: string) {
    super();
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code: number): void {
    this.closedWith = code;
    this.readyState = 3;
  }

  serverOpens(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatchEvent(new Event('open'));
  }

  serverSends(message: unknown): void {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }));
  }

  serverCloses(code: number): void {
    this.readyState = 3;
    this.dispatchEvent(new CloseEvent('close', { code }));
  }
}

const CANAL: Bbox = [-80.2, 8.4, -79.2, 9.7];
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

function lastSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) {
    throw new Error('No se abrió ningún WebSocket');
  }
  return socket;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('liveSocketUrl', () => {
  it('usa la misma origen con ws o wss según la página', () => {
    expect(liveSocketUrl('', { protocol: 'http:', host: 'localhost:5173' })).toBe(
      'ws://localhost:5173/ws/live',
    );
    expect(liveSocketUrl('', { protocol: 'https:', host: 'canal.example.com' })).toBe(
      'wss://canal.example.com/ws/live',
    );
  });

  it('usa VITE_API_URL si está definida', () => {
    expect(liveSocketUrl('https://api.example.com', { protocol: 'http:', host: 'x' })).toBe(
      'wss://api.example.com/ws/live',
    );
  });
});

describe('useLiveVessels', () => {
  it('sin token no abre conexión', () => {
    const { result } = renderHook(() => useLiveVessels(null, CANAL));

    expect(result.current.status).toBe('idle');
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it('se autentica en el primer mensaje, se suscribe y aplica los mensajes', () => {
    const { result } = renderHook(() => useLiveVessels('token-1', CANAL));
    const socket = lastSocket();

    expect(result.current.status).toBe('connecting');
    expect(socket.url).not.toContain('token');

    act(() => {
      socket.serverOpens();
    });
    expect(socket.sent).toEqual([
      { type: 'auth', token: 'token-1' },
      { type: 'subscribe', bbox: [...CANAL] },
    ]);
    expect(result.current.status).toBe('live');

    act(() => {
      socket.serverSends({ type: 'snapshot', vessels: [vessel] });
    });
    expect([...result.current.vessels.keys()]).toEqual([vessel.mmsi]);

    act(() => {
      socket.serverSends({ type: 'remove', mmsi: [vessel.mmsi] });
    });
    expect(result.current.vessels.size).toBe(0);
  });

  it('vuelve a suscribirse cuando cambia el viewport', () => {
    const { rerender } = renderHook(({ bbox }) => useLiveVessels('token-1', bbox), {
      initialProps: { bbox: CANAL },
    });
    const socket = lastSocket();
    act(() => {
      socket.serverOpens();
    });

    const moved: Bbox = [-80, 9, -79.5, 9.5];
    rerender({ bbox: moved });

    expect(socket.sent.at(-1)).toEqual({ type: 'subscribe', bbox: [...moved] });
  });

  it('cierra la conexión al desmontarse', () => {
    const { unmount } = renderHook(() => useLiveVessels('token-1', CANAL));
    const socket = lastSocket();

    unmount();

    expect(socket.closedWith).toBe(1000);
  });

  it('un token renovado no reabre la conexión: se usa en la siguiente', () => {
    vi.useFakeTimers();
    const { rerender } = renderHook(({ token }) => useLiveVessels(token, CANAL), {
      initialProps: { token: 'token-1' },
    });
    const first = lastSocket();
    act(() => {
      first.serverOpens();
    });

    rerender({ token: 'token-2' });
    expect(first.closedWith).toBeNull();
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      first.serverCloses(1012);
      vi.runOnlyPendingTimers();
    });
    act(() => {
      lastSocket().serverOpens();
    });
    expect(lastSocket().sent[0]).toEqual({ type: 'auth', token: 'token-2' });
  });

  it('al caerse reconecta, se suscribe otra vez y conserva los buques hasta el snapshot', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useLiveVessels('token-1', CANAL));
    const first = lastSocket();
    act(() => {
      first.serverOpens();
      first.serverSends({ type: 'snapshot', vessels: [vessel] });
      first.serverCloses(1006);
    });

    expect(result.current).toMatchObject({ status: 'reconnecting', closeCode: 1006 });
    expect(result.current.vessels.size).toBe(1);
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    const second = lastSocket();
    expect(second).not.toBe(first);
    act(() => {
      second.serverOpens();
    });

    expect(result.current.status).toBe('live');
    expect(second.sent).toEqual([
      { type: 'auth', token: 'token-1' },
      { type: 'subscribe', bbox: [...CANAL] },
    ]);
    act(() => {
      second.serverSends({ type: 'snapshot', vessels: [] });
    });
    expect(result.current.vessels.size).toBe(0);
  });

  it('las esperas crecen entre fallos seguidos y vuelven a empezar al conectar', () => {
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(1);
    renderHook(() => useLiveVessels('token-1', CANAL));

    const failAndWait = (ms: number) => {
      const before = FakeWebSocket.instances.length;
      act(() => {
        lastSocket().serverCloses(1006);
        vi.advanceTimersByTime(ms - 1);
      });
      expect(FakeWebSocket.instances).toHaveLength(before);
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(FakeWebSocket.instances).toHaveLength(before + 1);
    };

    failAndWait(1_000);
    failAndWait(2_000);
    failAndWait(4_000);
    act(() => {
      lastSocket().serverOpens();
    });
    failAndWait(1_000);
  });

  it('al volver la red reintenta sin esperar al backoff', () => {
    vi.useFakeTimers();
    renderHook(() => useLiveVessels('token-1', CANAL));
    act(() => {
      lastSocket().serverCloses(1006);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      window.dispatchEvent(new Event('online'));
    });

    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('con 4401 pide renovar el token y reconecta en cuanto llega otro', () => {
    vi.useFakeTimers();
    const onUnauthorized = vi.fn();
    const { result, rerender } = renderHook(
      ({ token }) => useLiveVessels(token, CANAL, onUnauthorized),
      { initialProps: { token: 'caducado' } },
    );
    act(() => {
      lastSocket().serverOpens();
      lastSocket().serverCloses(4401);
    });

    expect(onUnauthorized).toHaveBeenCalledWith('caducado');
    expect(result.current).toMatchObject({ status: 'reconnecting', closeCode: 4401 });
    // Con el mismo token no tiene sentido insistir.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    rerender({ token: 'renovado' });
    expect(FakeWebSocket.instances).toHaveLength(2);
    act(() => {
      lastSocket().serverOpens();
    });
    expect(lastSocket().sent[0]).toEqual({ type: 'auth', token: 'renovado' });
  });

  it('con 4400 (mensaje inválido: error del cliente) no reintenta', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useLiveVessels('token-1', CANAL));
    act(() => {
      lastSocket().serverOpens();
      lastSocket().serverCloses(4400);
      vi.advanceTimersByTime(60_000);
    });

    expect(result.current).toMatchObject({ status: 'closed', closeCode: 4400 });
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('al cerrar sesión deja de reintentar y olvida los buques', () => {
    vi.useFakeTimers();
    const initialProps: { token: string | null } = { token: 'token-1' };
    const { result, rerender } = renderHook(({ token }) => useLiveVessels(token, CANAL), {
      initialProps,
    });
    act(() => {
      lastSocket().serverOpens();
      lastSocket().serverSends({ type: 'snapshot', vessels: [vessel] });
      lastSocket().serverCloses(1006);
    });

    rerender({ token: null });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(result.current).toMatchObject({ status: 'idle', closeCode: null });
    expect(FakeWebSocket.instances).toHaveLength(1);

    rerender({ token: 'token-2' });
    expect(result.current).toMatchObject({ status: 'connecting' });
    expect(result.current.vessels.size).toBe(0);
  });
});

describe('reconnectDelay', () => {
  it('duplica el tramo en cada intento hasta 30 s, con jitter entre la mitad y el total', () => {
    expect(reconnectDelay(0, 1006, () => 1)).toBe(1_000);
    expect(reconnectDelay(0, 1006, () => 0)).toBe(500);
    expect(reconnectDelay(3, 1006, () => 1)).toBe(8_000);
    expect(reconnectDelay(10, 1006, () => 1)).toBe(30_000);
    expect(reconnectDelay(10, 1006, () => 0)).toBe(15_000);
  });

  it('con 4429 (demasiadas conexiones) espera al menos 15 s', () => {
    expect(reconnectDelay(0, 4429, () => 0)).toBe(15_000);
    expect(reconnectDelay(10, 4429, () => 1)).toBe(30_000);
  });
});
