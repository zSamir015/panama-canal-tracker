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

/** API de mentira: login, ficha y estela; `trackStatus` permite simular un token caducado. */
function stubApi(trackStatus = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith('/auth/login')) {
        return Promise.resolve(json(200, { access_token: 'abc', token_type: 'bearer' }));
      }
      if (url.endsWith('/history')) {
        return Promise.resolve(
          json(trackStatus, {
            type: 'Feature',
            geometry: null,
            properties: { timestamps: [], truncated: false },
          }),
        );
      }
      return Promise.resolve(json(200, detail));
    }),
  );
  // El WebSocket no se abre nunca: aquí solo importa la parte REST.
  vi.stubGlobal(
    'WebSocket',
    class extends EventTarget {
      static readonly OPEN = 1;
      close = vi.fn();
    },
  );
}

async function signIn() {
  await userEvent.type(screen.getByLabelText('Email'), 'demo@example.com');
  await userEvent.type(screen.getByLabelText('Contraseña'), 'changeme-changeme');
  await userEvent.click(screen.getByRole('button', { name: 'Entrar' }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('muestra el título y pide iniciar sesión antes del mapa (ADR-0008)', () => {
    renderWithQuery(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'Panama Canal Tracker' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Mapa en vivo' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
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

  it('vuelve al login si la API rechaza el token', async () => {
    stubApi(401);
    renderWithQuery(<App />);
    await signIn();

    await userEvent.click(await screen.findByRole('button', { name: 'buque de prueba' }));

    expect(await screen.findByText('La sesión caducó. Vuelve a iniciar sesión.')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
  });
});
