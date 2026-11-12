import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MapLegend } from './MapLegend';

// Plegar solo tiene efecto en móvil: el CSS oculta el botón en escritorio y allí la lista se ve
// siempre. jsdom no aplica ese CSS, así que aquí se comprueba el estado, no el aspecto.
describe('MapLegend', () => {
  it('empieza plegada y el botón dice qué lista controla', () => {
    const { container } = render(<MapLegend />);

    const toggle = screen.getByRole('button', { name: 'Leyenda' });
    const list = screen.getByRole('list', { name: 'Tipos de buque' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('aria-controls', list.id);
    expect(container.firstElementChild).toHaveClass('map-legend--collapsed');
  });

  it('se despliega y se vuelve a plegar al pulsar el botón', async () => {
    const { container } = render(<MapLegend />);
    const toggle = screen.getByRole('button', { name: 'Leyenda' });

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(container.firstElementChild).not.toHaveClass('map-legend--collapsed');

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('la lista está siempre en el documento, con todos los tipos', () => {
    render(<MapLegend />);

    expect(screen.getAllByRole('listitem')).toHaveLength(8);
  });
});
