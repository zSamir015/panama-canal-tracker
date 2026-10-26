import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { renderWithQuery } from './test/render';

// MapLibre necesita WebGL, que jsdom no tiene: el mapa se sustituye por un botón que "hace clic"
// en un buque, y su lógica se prueba por separado.
vi.mock('./map/VesselMap', () => ({
  VesselMap: ({ onSelect }: { onSelect: (mmsi: number | null) => void }) => (
    <button
      type="button"
      onClick={() => {
        onSelect(352001234);
      }}
    >
      buque de prueba
    </button>
  ),
}));

const detail = {
  mmsi: 352001234,
  name: '<img src=x onerror=alert(1)>',
  imo: 9301234,
  ship_type: 70,
  length_m: 225,
  beam_m: 32,
  last_seen_at: '2026-10-23T17:00:00Z',
  last_position: null,
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface StubOptions {
  /** Códigos de `/auth/refresh`, uno por petición (el último se repite); 401 = sin sesión. */
  refreshStatuses?: number[];
  /** Códigos que devuelve la estela, uno por petición (el último se repite). */
  trackStatuses?: number[];
  /** Nombre que devuelve la ficha REST (por defecto, el hostil de `detail`). */
  detailName?: string;
}

/** API de mentira: login, refresh, ficha y estela. */
function stubApi({
  refreshStatuses = [401],
  trackStatuses = [200],
  detailName = detail.name,
}: StubOptions = {}) {
  const next = (pending: number[]) => (pending.length > 1 ? pending.shift() : pending[0]) ?? 200;
  const pendingRefresh = [...refreshStatuses];
  const pendingTrack = [...trackStatuses];
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>((url) => {
    if (url.endsWith('/auth/login')) {
      return Promise.resolve(json(200, { access_token: 'abc', token_type: 'bearer' }));
    }
    if (url.endsWith('/auth/refresh')) {
      return Promise.resolve(
        json(next(pendingRefresh), {
          access_token: 'renovado',
          token_type: 'bearer',
          expires_in: 900,
        }),
      );
    }
    if (url.endsWith('/history')) {
      return Promise.resolve(
        json(next(pendingTrack), {
          type: 'Feature',
          geometry: null,
          properties: { timestamps: [], truncated: false },
        }),
      );
    }
    return Promise.resolve(json(200, { ...detail, name: detailName }));
  });
  vi.stubGlobal('fetch', fetchMock);
  // El WebSocket no se abre nunca: aquí solo importa la parte REST.
  vi.stubGlobal(
    'WebSocket',
    class extends EventTarget {
      static readonly OPEN = 1;
      close = vi.fn();
    },
  );
  return fetchMock;
}

async function signIn() {
  await screen.findByRole('heading', { name: 'Iniciar sesión' });
  await userEvent.type(screen.getByLabelText('Email'), 'demo@example.com');
  await userEvent.type(screen.getByLabelText('Contraseña'), 'changeme-changeme');
  await userEvent.click(screen.getByRole('button', { name: 'Entrar' }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('muestra el título y pide iniciar sesión antes del mapa (ADR-0008)', async () => {
    stubApi();
    renderWithQuery(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'Panama Canal Tracker' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Mapa en vivo' })).toBeInTheDocument();
    expect(screen.getByText('Recuperando la sesión…')).toBeVisible();
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    // Sin sesión previa no hay aviso de caducidad.
    expect(screen.queryByText(/caducó/)).not.toBeInTheDocument();
  });

  it('al recargar recupera la sesión con la cookie, sin pedir entrar', async () => {
    stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    expect(await screen.findByRole('button', { name: 'buque de prueba' })).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Conectando…');
    expect(screen.queryByRole('heading', { name: 'Iniciar sesión' })).not.toBeInTheDocument();
  });

  it('si la API rechaza el token, lo renueva y sigue con el nuevo', async () => {
    // Al cargar no hay sesión; después del login, la renovación sí la encuentra.
    const fetchMock = stubApi({ refreshStatuses: [401, 200], trackStatuses: [401, 200] });
    renderWithQuery(<App />);
    await signIn();

    await userEvent.click(await screen.findByRole('button', { name: 'buque de prueba' }));

    await vi.waitFor(() => {
      const authorizations = fetchMock.mock.calls
        .filter(([url]) => url.endsWith('/history'))
        .map(([, init]) => new Headers(init?.headers).get('Authorization'));
      expect(authorizations).toEqual(['Bearer abc', 'Bearer renovado']);
    });
    expect(screen.queryByRole('heading', { name: 'Iniciar sesión' })).not.toBeInTheDocument();
  });

  it('abre la ficha al hacer clic en un buque y la cierra con Escape', async () => {
    stubApi();
    renderWithQuery(<App />);
    await signIn();

    await userEvent.click(await screen.findByRole('button', { name: 'buque de prueba' }));

    const panel = await screen.findByRole('complementary', { name: 'Ficha del buque' });
    // El nombre hostil se ve como texto: ni etiqueta <img> ni manejador de eventos.
    expect(await screen.findByRole('heading', { name: detail.name })).toBeVisible();
    expect(panel.querySelector('img')).toBeNull();
    expect(panel).toHaveTextContent('Carga (70)');

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  });

  it('vuelve al login si la API rechaza el token y ya no hay sesión que renovar', async () => {
    stubApi({ trackStatuses: [401] });
    renderWithQuery(<App />);
    await signIn();

    await userEvent.click(await screen.findByRole('button', { name: 'buque de prueba' }));

    expect(await screen.findByText('La sesión caducó. Vuelve a iniciar sesión.')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
  });

  it('un nombre hostil que llega por /ws/live se muestra como texto (AGENTS.md §8.7)', async () => {
    stubApi({ detailName: 'NOMBRE REST' });
    const hostile = '<img src=x onerror=alert(1)>';
    // WebSocket de mentira: al recibir la suscripción contesta con un snapshot del buque.
    vi.stubGlobal(
      'WebSocket',
      class extends EventTarget {
        static readonly OPEN = 1;
        readyState = 0;
        constructor() {
          super();
          queueMicrotask(() => {
            this.readyState = 1;
            this.dispatchEvent(new Event('open'));
          });
        }
        send(data: string) {
          if ((JSON.parse(data) as { type: string }).type !== 'auth') {
            return;
          }
          const vessel = {
            mmsi: detail.mmsi,
            lon: -79.91,
            lat: 9.35,
            cog: 145,
            sog: 7.8,
            ship_type: 70,
            name: hostile,
            ts: '2026-10-25T17:00:00Z',
          };
          queueMicrotask(() => {
            this.dispatchEvent(
              new MessageEvent('message', {
                data: JSON.stringify({ type: 'snapshot', vessels: [vessel] }),
              }),
            );
          });
        }
        close = vi.fn();
      },
    );
    renderWithQuery(<App />);
    await signIn();
    expect(await screen.findByRole('status')).toHaveTextContent('En vivo · 1 buques');

    await userEvent.click(screen.getByRole('button', { name: 'buque de prueba' }));

    // La ficha prefiere el nombre en vivo: llega intacto, pero como texto.
    expect(await screen.findByRole('heading', { name: hostile })).toBeVisible();
    expect(screen.queryByText('NOMBRE REST')).not.toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });
});
