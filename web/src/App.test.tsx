import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('App', () => {
  it('muestra el título y el hueco del mapa', () => {
    render(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'Panama Canal Tracker' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Mapa en vivo' })).toBeInTheDocument();
  });
});
