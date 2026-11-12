import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { LiveStatus } from '../live/useLiveVessels';
import { connectionTone } from './connection';
import { ConnectionDot } from './ConnectionDot';
import { Skeleton } from './Skeleton';

describe('Skeleton', () => {
  it('dibuja las líneas pedidas, ocultas al lector de pantalla, y dice "Cargando…"', () => {
    const { container } = render(<Skeleton lines={4} />);

    const skeleton = container.firstElementChild;
    expect(skeleton).toHaveAttribute('aria-busy', 'true');
    expect(skeleton?.querySelectorAll('.skeleton__line[aria-hidden="true"]')).toHaveLength(4);
    // El texto no se ve (clase `visually-hidden`), pero el lector de pantalla lo lee.
    expect(screen.getByText('Cargando…')).toHaveClass('visually-hidden');
  });

  it('la variante de gráfica es un solo bloque', () => {
    const { container } = render(<Skeleton variant="chart" />);

    expect(container.querySelectorAll('.skeleton__block')).toHaveLength(1);
    expect(container.querySelectorAll('.skeleton__line')).toHaveLength(0);
  });

  // Otro `role="status"` chocaría con el estado de la conexión, que ya lo usa.
  it('no es una región viva: no compite con el estado de la conexión', () => {
    render(<Skeleton />);

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('connectionTone', () => {
  it.each<[LiveStatus, string]>([
    ['live', 'ok'],
    ['connecting', 'pending'],
    ['reconnecting', 'pending'],
    ['idle', 'down'],
    ['closed', 'down'],
  ])('%s se pinta como %s', (status, tone) => {
    expect(connectionTone(status)).toBe(tone);
  });
});

describe('ConnectionDot', () => {
  it('es solo decorativo: el estado lo dice el texto de al lado', () => {
    const { container } = render(<ConnectionDot status="reconnecting" />);

    const dot = container.firstElementChild;
    expect(dot).toHaveAttribute('aria-hidden', 'true');
    expect(dot).toHaveClass('connection-dot', 'connection-dot--pending');
    expect(dot).toHaveTextContent('');
  });
});
