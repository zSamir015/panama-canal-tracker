import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';

// MapLibre necesita WebGL, que jsdom no tiene: el mapa se prueba a mano y su lógica por separado.
vi.mock('./map/VesselMap', () => ({ VesselMap: () => null }));

describe('App', () => {
  it('muestra el título y pide iniciar sesión antes del mapa (ADR-0008)', () => {
    render(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'Panama Canal Tracker' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Mapa en vivo' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeVisible();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
