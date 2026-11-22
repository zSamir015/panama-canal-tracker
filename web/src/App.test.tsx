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
    if (url.includes('/stats/daily')) {
      return Promise.resolve(json(200, { items: [] }));
    }
    if (url.includes('/stats/transit-durations')) {
      const empty = { count: 0, mean_minutes: null, p50_minutes: null, p90_minutes: null };
      return Promise.resolve(
        json(200, { overall: empty, by_direction: { northbound: empty, southbound: empty } }),
      );
    }
    if (url.includes('/stats/waiting-times')) {
      const empty = { count: 0, mean_minutes: null, p50_minutes: null, p90_minutes: null };
      return Promise.resolve(
        json(200, { overall: empty, by_anchorage: { atlantic: empty, pacific: empty } }),
      );
    }
    if (url.endsWith('/transits/current')) {
      return Promise.resolve(json(200, { items: [], total: 0 }));
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
    if (url.includes('/vessels?size=200')) {
      return Promise.resolve(
        json(200, {
          items: [
            {
              mmsi: 352001234,
              name: 'PACIFIC STAR',
              imo: 9301234,
              ship_type: 70,
              last_seen_at: '2026-10-23T17:00:00Z',
              last_position: { lat: 9.0, lon: -79.5 },
            },
          ],
          total: 1,
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
  window.history.replaceState(null, '', '/');
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
    expect(panel).toHaveTextContent('Carga');
    expect(panel).toHaveTextContent('Código AIS70');

    await userEvent.keyboard('{Escape}');
    expect(
      screen.queryByRole('complementary', { name: 'Ficha del buque' }),
    ).not.toBeInTheDocument();
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
    // El punto verde acompaña al texto; no lo sustituye.
    expect(screen.getByRole('status').querySelector('.connection-dot--ok')).not.toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'buque de prueba' }));

    // La ficha prefiere el nombre en vivo: llega intacto, pero como texto.
    expect(await screen.findByRole('heading', { name: hostile })).toBeVisible();
    expect(screen.queryByText('NOMBRE REST')).not.toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });

  it('cambia entre el mapa y las estadísticas con las pestañas y las flechas', async () => {
    window.localStorage.setItem('panama-canal-tracker:guide-seen', '1');
    stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    expect(await screen.findByRole('button', { name: 'buque de prueba' })).toBeVisible();
    const mapTab = screen.getByRole('tab', { name: 'Mapa' });
    const statsTab = screen.getByRole('tab', { name: 'Estadísticas' });
    expect(mapTab).toHaveAttribute('aria-selected', 'true');
    expect(statsTab).toHaveAttribute('aria-selected', 'false');
    expect(screen.queryByRole('region', { name: 'Estadísticas' })).not.toBeInTheDocument();

    mapTab.focus();
    await userEvent.keyboard('{ArrowRight}');

    expect(await screen.findByRole('region', { name: 'Estadísticas' })).toBeVisible();
    expect(statsTab).toHaveAttribute('aria-selected', 'true');
    expect(window.location.search).toContain('view=stats');
    expect(screen.queryByRole('region', { name: 'Mapa en vivo' })).not.toBeInTheDocument();
    expect(await screen.findByText('No hay tránsitos completados en este periodo.')).toBeVisible();

    await userEvent.click(mapTab);

    expect(await screen.findByRole('button', { name: 'buque de prueba' })).toBeVisible();
    expect(window.location.search).toBe('');
    expect(screen.queryByRole('region', { name: 'Estadísticas' })).not.toBeInTheDocument();
  });

  it('abre el historial y, al elegir un buque, lo muestra en el mapa con su ficha', async () => {
    window.localStorage.setItem('panama-canal-tracker:guide-seen', '1');
    stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    await screen.findByRole('button', { name: 'buque de prueba' });
    await userEvent.click(screen.getByRole('tab', { name: 'Historial' }));

    expect(await screen.findByRole('region', { name: 'Historial' })).toBeVisible();
    expect(window.location.search).toContain('view=history');
    await userEvent.click(await screen.findByRole('button', { name: /PACIFIC STAR/ }));

    expect(screen.queryByRole('region', { name: 'Historial' })).not.toBeInTheDocument();
    expect(await screen.findByRole('region', { name: 'Mapa en vivo' })).toBeVisible();
    expect(window.location.search).toBe('?mmsi=352001234');
  });

  it('sincroniza el MMSI seleccionado con la URL y responde al buscador global con /', async () => {
    window.localStorage.setItem('panama-canal-tracker:guide-seen', '1');
    stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    await screen.findByRole('button', { name: 'buque de prueba' });
    await userEvent.keyboard('/');
    const search = screen.getByRole('combobox', { name: 'Buscar buque por nombre, MMSI o IMO' });
    await userEvent.type(search, '9301234');
    await userEvent.keyboard('{Enter}');

    expect(window.location.search).toBe('?mmsi=352001234');
    expect(
      await screen.findByRole('heading', { name: '<img src=x onerror=alert(1)>' }),
    ).toBeVisible();
  });

  it('permite entrar a la demo simulada sin cuenta desde el login', async () => {
    window.localStorage.setItem('panama-canal-tracker:guide-seen', '1');
    stubApi();
    renderWithQuery(<App />);

    await screen.findByRole('heading', { name: 'Iniciar sesión' });
    await userEvent.click(screen.getByRole('button', { name: 'Ver demo sin cuenta' }));

    expect(await screen.findByText(/Datos simulados/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'buque de prueba' })).toBeVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Volver al inicio de sesión' }));
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
  });

  it('no enseña las pestañas antes de iniciar sesión', async () => {
    stubApi();
    renderWithQuery(<App />);

    await screen.findByRole('heading', { name: 'Iniciar sesión' });

    expect(screen.queryByRole('navigation', { name: 'Vista' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cerrar sesión' })).not.toBeInTheDocument();
  });

  it('cierra la sesión desde la cabecera y vuelve al login sin aviso de caducidad', async () => {
    const fetchMock = stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    const logoutBtn = await screen.findByRole('button', { name: 'Cerrar sesión' });
    await userEvent.click(logoutBtn);

    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
    expect(screen.queryByText(/caducó/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/logout'))).toBe(true);
  });
  it('alterna tema oscuro/claro, capa satelital y colapso del panel lateral', async () => {
    window.localStorage.setItem('panama-canal-tracker:guide-seen', '1');
    stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    await screen.findByRole('button', { name: 'buque de prueba' });

    const themeBtn = screen.getByRole('button', { name: 'Cambiar a tema oscuro' });
    await userEvent.click(themeBtn);
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.getByRole('button', { name: 'Cambiar a tema claro' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    const satBtn = screen.getByRole('button', { name: 'Satélite' });
    await userEvent.click(satBtn);
    expect(satBtn).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Estándar' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ocultar panel lateral' }));
    const expandBtn = screen.getByRole('button', { name: 'Mostrar panel lateral' });
    expect(expandBtn).toBeVisible();
    await userEvent.click(expandBtn);
    expect(screen.queryByRole('button', { name: 'Mostrar panel lateral' })).not.toBeInTheDocument();

    // Restaurar estado limpio para otros tests.
    await userEvent.click(screen.getByRole('button', { name: 'Cambiar a tema claro' }));
    await userEvent.click(screen.getByRole('button', { name: 'Estándar' }));
  });
});

describe('Guía al primer uso (issue #137)', () => {
  const guide = () => screen.queryByRole('dialog', { name: 'Cómo usar el tracker' });

  it('no sale encima del login; sale al ver el mapa por primera vez', async () => {
    stubApi();
    renderWithQuery(<App />);

    await screen.findByRole('heading', { name: 'Iniciar sesión' });
    expect(guide()).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cómo usar el tracker' })).not.toBeInTheDocument();

    await signIn();
    expect(await screen.findByRole('dialog', { name: 'Cómo usar el tracker' })).toBeVisible();
  });

  it('al cerrarla se recuerda y no vuelve a salir sola', async () => {
    stubApi({ refreshStatuses: [200] });
    const { unmount } = renderWithQuery(<App />);
    await screen.findByRole('dialog', { name: 'Cómo usar el tracker' });

    await userEvent.click(screen.getByRole('button', { name: 'Entendido' }));
    expect(guide()).not.toBeInTheDocument();

    unmount();
    renderWithQuery(<App />);
    await screen.findByRole('button', { name: 'buque de prueba' });
    expect(guide()).not.toBeInTheDocument();
  });

  it('el botón "?" de la cabecera la vuelve a abrir', async () => {
    window.localStorage.setItem('panama-canal-tracker:guide-seen', '1');
    stubApi({ refreshStatuses: [200] });
    renderWithQuery(<App />);

    const help = await screen.findByRole('button', { name: 'Cómo usar el tracker' });
    expect(help).toHaveAttribute('aria-haspopup', 'dialog');
    expect(guide()).not.toBeInTheDocument();

    await userEvent.click(help);
    expect(guide()).toBeVisible();
  });
});
