import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GuideDialog } from './GuideDialog';
import { GUIDE_SEEN_KEY, hasSeenGuide, rememberGuideSeen } from './guideStorage';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('guideStorage', () => {
  it('empieza sin ver y recuerda la guía vista', () => {
    expect(hasSeenGuide()).toBe(false);
    rememberGuideSeen();
    expect(hasSeenGuide()).toBe(true);
    expect(window.localStorage.getItem(GUIDE_SEEN_KEY)).toBe('1');
  });

  it('si el navegador bloquea el almacenamiento, la guía sale y nada falla', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError');
    });
    expect(hasSeenGuide()).toBe(false);
    expect(() => {
      rememberGuideSeen();
    }).not.toThrow();
  });
});

describe('GuideDialog', () => {
  it('abierta, es un diálogo con título y los pasos de la app real', () => {
    render(<GuideDialog open demo={false} onClose={vi.fn()} />);
    const dialog = screen.getByRole('dialog', { name: 'Cómo usar el tracker' });
    const steps = within(dialog).getAllByRole('listitem');
    expect(steps).toHaveLength(4);
    expect(within(dialog).getByRole('button', { name: 'Entendido' })).toHaveFocus();
    expect(dialog).toHaveTextContent(/ficha/);
    expect(dialog).toHaveTextContent(/En tránsito ahora/);
    expect(dialog).toHaveTextContent(/Estadísticas/);
  });

  it('en la demo explica lo que hay y avisa de que los datos son simulados', () => {
    render(<GuideDialog open demo onClose={vi.fn()} />);
    const dialog = screen.getByRole('dialog', { name: 'Cómo usar el tracker' });
    expect(dialog).toHaveTextContent(/simulados/);
    // En la demo no hay ficha, panel de tránsitos ni estadísticas (ADR-0011).
    expect(dialog).not.toHaveTextContent(/En tránsito ahora/);
    expect(dialog).not.toHaveTextContent(/Estadísticas/);
  });

  it('cerrada, no se muestra', () => {
    render(<GuideDialog open={false} demo={false} onClose={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('"Entendido" y la ✕ la cierran y avisan', async () => {
    const onClose = vi.fn();
    const { rerender } = render(<GuideDialog open demo={false} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: 'Entendido' }));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<GuideDialog open={false} demo={false} onClose={onClose} />);
    rerender(<GuideDialog open demo={false} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar la guía' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('Escape dentro de la guía no llega a window (allí escucha la ficha del buque)', () => {
    const onWindowKey = vi.fn();
    window.addEventListener('keydown', onWindowKey);
    render(<GuideDialog open demo={false} onClose={vi.fn()} />);
    fireEvent.keyDown(screen.getByRole('button', { name: 'Entendido' }), { key: 'Escape' });
    window.removeEventListener('keydown', onWindowKey);
    expect(onWindowKey).not.toHaveBeenCalled();
  });
});
