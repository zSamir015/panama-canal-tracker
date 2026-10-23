import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Bbox } from './protocol';
import { liveSocketUrl, useLiveVessels } from './useLiveVessels';

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

  it('expone el código de cierre (4401: token inválido)', () => {
    const { result } = renderHook(() => useLiveVessels('token-1', CANAL));
    const socket = lastSocket();

    act(() => {
      socket.serverOpens();
      socket.serverCloses(4401);
    });

    expect(result.current).toMatchObject({ status: 'closed', closeCode: 4401 });
  });

  it('cierra la conexión al desmontarse y con un token nuevo', () => {
    const { rerender, unmount } = renderHook(({ token }) => useLiveVessels(token, CANAL), {
      initialProps: { token: 'token-1' },
    });
    const first = lastSocket();

    rerender({ token: 'token-2' });
    expect(first.closedWith).toBe(1000);

    const second = lastSocket();
    unmount();
    expect(second.closedWith).toBe(1000);
  });
});
