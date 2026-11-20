import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { LiveVessel } from '../live/protocol';
import { MapSidebar } from './MapSidebar';

const vessels = new Map<number, LiveVessel>([
  [
    352000001,
    {
      mmsi: 352000001,
      lon: -79.92,
      lat: 9.3,
      cog: 180,
      sog: 8.5,
      ship_type: 70,
      name: 'PACIFIC STAR',
      ts: '2026-10-25T12:00:00Z',
    },
  ],
  [
    636000002,
    {
      mmsi: 636000002,
      lon: -79.59,
      lat: 9.0,
      cog: 315,
      sog: 6.2,
      ship_type: 80,
      name: 'ATLANTIC DAWN',
      ts: '2026-10-25T12:00:00Z',
    },
  ],
  [
    371000005,
    {
      mmsi: 371000005,
      lon: -79.87,
      lat: 9.42,
      cog: null,
      sog: 0.1,
      ship_type: 70,
      name: 'COLON BREEZE',
      ts: '2026-10-25T12:00:00Z',
    },
  ],
]);

describe('MapSidebar', () => {
  it('filtra buques por nombre o MMSI y por tipo de buque', async () => {
    const onSelectVessel = vi.fn();
    render(
      <MapSidebar
        vessels={vessels}
        selectedMmsi={null}
        onSelectVessel={onSelectVessel}
        onClearSelection={vi.fn()}
        demo={false}
        transitsCount={2}
        collapsed={false}
        onToggleCollapse={vi.fn()}
        detailSlot={null}
        transitsSlot={<div>tránsitos mock</div>}
      />,
    );

    expect(screen.getByText('PACIFIC STAR')).toBeVisible();
    expect(screen.getByText('ATLANTIC DAWN')).toBeVisible();
    expect(screen.getByText('Fondeado')).toBeVisible();

    const search = screen.getByRole('searchbox', { name: 'Buscar buques por nombre o MMSI' });
    await userEvent.type(search, '636000002');
    expect(screen.getByText('ATLANTIC DAWN')).toBeVisible();
    expect(screen.queryByText('PACIFIC STAR')).not.toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.click(screen.getByRole('button', { name: /Tanquero \(1\)/ }));
    expect(screen.getByText('ATLANTIC DAWN')).toBeVisible();
    expect(screen.queryByText('COLON BREEZE')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /ATLANTIC DAWN/ }));
    expect(onSelectVessel).toHaveBeenCalledWith(vessels.get(636000002));
  });

  it('cambia entre Buques y En tránsito y dispara colapso del panel', async () => {
    const onToggleCollapse = vi.fn();
    render(
      <MapSidebar
        vessels={vessels}
        selectedMmsi={null}
        onSelectVessel={vi.fn()}
        onClearSelection={vi.fn()}
        demo={false}
        transitsCount={2}
        collapsed={false}
        onToggleCollapse={onToggleCollapse}
        detailSlot={null}
        transitsSlot={<div>lista de tránsitos</div>}
      />,
    );

    await userEvent.click(screen.getByRole('tab', { name: /En tránsito/ }));
    expect(screen.getByText('lista de tránsitos')).toBeVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Ocultar panel lateral' }));
    expect(onToggleCollapse).toHaveBeenCalledTimes(1);
  });
});
