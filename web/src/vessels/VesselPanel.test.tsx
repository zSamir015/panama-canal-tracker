import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CATEGORY_COLORS } from '../map/vesselGeoJson';
import { renderWithQuery } from '../test/render';
import { VesselPanel } from './VesselPanel';

const detail = {
  mmsi: 352001234,
  name: 'EXAMPLE',
  imo: 9100007,
  ship_type: 70,
  length_m: 225.4,
  beam_m: 32,
  last_seen_at: '2026-10-23T17:00:00Z',
  last_position: {
    received_at: '2026-10-23T17:00:00Z',
    lat: 9.35,
    lon: -79.91,
    sog: 7.8,
    cog: 145.2,
    heading: null,
    nav_status: 0,
  },
};

function stubDetail(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(Response.json(body))),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/** jsdom guarda los colores en `rgb()`. */
function rgb(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
  return `rgb(${String(r)}, ${String(g)}, ${String(b)})`;
}

function renderPanel() {
  return renderWithQuery(
    <VesselPanel mmsi={detail.mmsi} token="abc" live={undefined} onClose={vi.fn()} />,
  );
}

describe('VesselPanel', () => {
  it('muestra el tipo como etiqueta con el color del mapa y el MMSI aparte', async () => {
    stubDetail(detail);
    renderPanel();

    const badge = await screen.findByText('Carga');
    expect(badge).toHaveClass('vessel-panel__type');
    // El color va en el punto; el texto se queda oscuro para que siempre se lea (WCAG AA).
    const swatch = badge.querySelector('.vessel-panel__swatch');
    expect(swatch).toHaveStyle({ backgroundColor: rgb(CATEGORY_COLORS.cargo) });
    expect(screen.getByText('MMSI 352001234')).toHaveClass('vessel-panel__mmsi');
  });

  it('agrupa los datos en Movimiento y Buque', async () => {
    stubDetail(detail);
    renderPanel();
    await screen.findByText('Carga');

    const movement = screen.getByRole('group', { name: 'Movimiento' });
    const vessel = screen.getByRole('group', { name: 'Buque' });
    expect(within(movement).getByText('7.8 nudos')).toBeVisible();
    expect(within(movement).getByText('145°')).toBeVisible();
    expect(within(movement).getByText('Navegando con motor')).toBeVisible();
    expect(within(vessel).getByText('9100007')).toBeVisible();
    expect(within(vessel).getByText('225 m × 32 m')).toBeVisible();
    expect(within(vessel).getByText('Código AIS')).toBeVisible();
    expect(within(vessel).getByText('70')).toBeVisible();
  });

  it('sin tipo AIS dice "Sin tipo" y deja el código con un guion', async () => {
    stubDetail({ ...detail, ship_type: null, imo: null });
    renderPanel();

    // Sin datos todavía el tipo también es "Sin tipo": se espera a que llegue la ficha.
    await screen.findByText('225 m × 32 m');
    expect(screen.getByText('Sin tipo')).toHaveClass('vessel-panel__type');
    const vessel = screen.getByRole('group', { name: 'Buque' });
    expect(within(vessel).getAllByText('—')).toHaveLength(2);
  });

  it('mientras carga muestra un esqueleto en lugar de los datos', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    );
    const { container } = renderPanel();

    expect(container.querySelector('.skeleton[aria-busy="true"]')).not.toBeNull();
    expect(screen.getByText('Cargando…')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Movimiento' })).not.toBeInTheDocument();
  });

  it('un nombre hostil se pinta como texto en la cabecera', async () => {
    const hostile = '<img src=x onerror=alert(1)>';
    stubDetail({ ...detail, name: hostile });
    const { container } = renderPanel();

    expect(await screen.findByRole('heading', { name: hostile })).toBeVisible();
    expect(container.querySelector('img')).toBeNull();
  });
});
