import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { renderWithQuery } from '../test/render';
import { fetchCurrentTransits, parseCurrentTransits } from './api';
import { directionText, elapsedText, transitName } from './format';
import { TransitsPanel } from './TransitsPanel';

const item = {
  id: '3f0c2a52-0000-4000-8000-000000000001',
  mmsi: 352000001,
  vessel_name: 'PACIFIC STAR',
  ship_type: 70,
  direction: 'southbound',
  status: 'in_progress',
  abort_reason: null,
  entered_at: '2026-11-06T10:00:00Z',
  exited_at: null,
  duration_minutes: null,
};

const body = { items: [item], total: 1 };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseCurrentTransits', () => {
  it('acepta la respuesta de la API y se queda con lo que usa el panel', () => {
    expect(parseCurrentTransits(body)).toEqual({
      items: [
        {
          id: item.id,
          mmsi: item.mmsi,
          vessel_name: 'PACIFIC STAR',
          ship_type: 70,
          direction: 'southbound',
          entered_at: item.entered_at,
        },
      ],
      total: 1,
    });
    expect(parseCurrentTransits({ items: [], total: 0 })).toEqual({ items: [], total: 0 });
    expect(
      parseCurrentTransits({ items: [{ ...item, vessel_name: null, ship_type: null }], total: 1 }),
    ).not.toBeNull();
  });

  it.each([
    ['un array', []],
    ['sin items', { total: 0 }],
    ['total negativo', { items: [], total: -1 }],
    ['total decimal', { items: [], total: 1.5 }],
    ['MMSI decimal', { items: [{ ...item, mmsi: 1.5 }], total: 1 }],
    ['sentido desconocido', { items: [{ ...item, direction: 'east' }], total: 1 }],
    ['nombre que no es texto', { items: [{ ...item, vessel_name: 7 }], total: 1 }],
    ['fecha inválida', { items: [{ ...item, entered_at: 'ayer' }], total: 1 }],
    ['sin id', { items: [{ ...item, id: undefined }], total: 1 }],
    ['un elemento roto entre buenos', { items: [item, { mmsi: 'x' }], total: 2 }],
  ])('rechaza %s', (_label, response) => {
    expect(parseCurrentTransits(response)).toBeNull();
  });
});

describe('fetchCurrentTransits', () => {
  it('pide la lista con el token en la cabecera, nunca en la URL', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(body)));

    await fetchCurrentTransits('abc', fetchImpl);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/transits/current');
    expect(init?.headers).toEqual({ Authorization: 'Bearer abc' });
  });

  it('convierte un 401 en ApiError y una forma inesperada en error', async () => {
    const unauthorized = vi.fn<typeof fetch>(() =>
      Promise.resolve(Response.json({}, { status: 401 })),
    );
    const odd = vi.fn<typeof fetch>(() => Promise.resolve(Response.json({ items: 3 })));

    await expect(fetchCurrentTransits('abc', unauthorized)).rejects.toBeInstanceOf(ApiError);
    await expect(fetchCurrentTransits('abc', odd)).rejects.toThrow('inesperada');
  });
});

describe('formatos', () => {
  it('dice el sentido con los nombres de las entradas', () => {
    expect(directionText('southbound')).toBe('Atlántico → Pacífico');
    expect(directionText('northbound')).toBe('Pacífico → Atlántico');
  });

  it('dice cuánto lleva en el Canal', () => {
    const now = Date.parse('2026-11-06T12:15:00Z');

    expect(elapsedText('2026-11-06T12:14:40Z', now)).toBe('acaba de entrar');
    expect(elapsedText('2026-11-06T11:45:00Z', now)).toBe('lleva 30 min');
    expect(elapsedText('2026-11-06T10:00:00Z', now)).toBe('lleva 2 h 15 min');
    expect(elapsedText('2026-11-06T09:15:00Z', now)).toBe('lleva 3 h');
    expect(elapsedText('2026-11-06T13:00:00Z', now)).toBe('acaba de entrar'); // reloj adelantado
    expect(elapsedText('no es una fecha', now)).toBe('—');
  });

  it('usa el MMSI cuando el nombre falta o es solo espacios', () => {
    expect(transitName('  EXAMPLE  ', 1)).toBe('EXAMPLE');
    expect(transitName('   ', 352000001)).toBe('MMSI 352000001');
    expect(transitName(null, 352000001)).toBe('MMSI 352000001');
  });
});

function stubTransits(response: () => Response) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
    Promise.resolve(response()),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('TransitsPanel', () => {
  it('lista los buques en tránsito y selecciona el que se pulsa', async () => {
    stubTransits(() =>
      Response.json({
        items: [item, { ...item, id: 'otro', mmsi: 636000002, vessel_name: 'ATLANTIC DAWN' }],
        total: 2,
      }),
    );
    const onSelect = vi.fn();
    renderWithQuery(<TransitsPanel token="abc" selectedMmsi={636000002} onSelect={onSelect} />);

    expect(await screen.findByText('PACIFIC STAR')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'En tránsito ahora (2)' })).toBeVisible();
    expect(screen.getAllByText(/Atlántico → Pacífico/)).toHaveLength(2);
    expect(screen.getByRole('button', { name: /ATLANTIC DAWN/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await userEvent.click(screen.getByRole('button', { name: /PACIFIC STAR/ }));

    expect(onSelect).toHaveBeenCalledWith(352000001);
  });

  // El plegado solo se ve en móvil (el CSS oculta el botón en escritorio); aquí, el estado.
  it('empieza plegado en una barra y se despliega al pulsarla', async () => {
    stubTransits(() => Response.json(body));
    const { container } = renderWithQuery(
      <TransitsPanel token="abc" selectedMmsi={null} onSelect={vi.fn()} />,
    );
    await screen.findByText('PACIFIC STAR');

    const toggle = screen.getByRole('button', { name: 'Lista de tránsitos' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(
      container.querySelector(`#${toggle.getAttribute('aria-controls') ?? ''}`),
    ).toContainElement(screen.getByText('PACIFIC STAR'));

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(container.firstElementChild).toHaveClass('transits-panel--expanded');
  });

  it('se pliega al elegir un buque, para dejar sitio a su ficha', async () => {
    stubTransits(() => Response.json(body));
    const onSelect = vi.fn();
    renderWithQuery(<TransitsPanel token="abc" selectedMmsi={null} onSelect={onSelect} />);
    await screen.findByText('PACIFIC STAR');
    const toggle = screen.getByRole('button', { name: 'Lista de tránsitos' });
    await userEvent.click(toggle);

    await userEvent.click(screen.getByRole('button', { name: /PACIFIC STAR/ }));

    expect(onSelect).toHaveBeenCalledWith(352000001);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('mientras carga muestra un esqueleto', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    );
    const { container } = renderWithQuery(
      <TransitsPanel token="abc" selectedMmsi={null} onSelect={vi.fn()} />,
    );

    expect(container.querySelector('.skeleton[aria-busy="true"]')).not.toBeNull();
    expect(screen.getByText('Cargando…')).toBeInTheDocument();
  });

  it('avisa cuando no hay ninguno', async () => {
    stubTransits(() => Response.json({ items: [], total: 0 }));
    renderWithQuery(<TransitsPanel token="abc" selectedMmsi={null} onSelect={vi.fn()} />);

    expect(await screen.findByText('Ningún buque en tránsito.')).toBeVisible();
  });

  it('avisa cuando la API recortó la lista', async () => {
    stubTransits(() => Response.json({ items: [item], total: 250 }));
    renderWithQuery(<TransitsPanel token="abc" selectedMmsi={null} onSelect={vi.fn()} />);

    expect(await screen.findByText('Se muestran 1 de 250.')).toBeVisible();
  });

  it('enseña el error de la API sin romper', async () => {
    stubTransits(() => Response.json({}, { status: 500 }));
    renderWithQuery(<TransitsPanel token="abc" selectedMmsi={null} onSelect={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('La API no respondió bien');
  });

  it('pinta un nombre con marcado HTML como texto, no como HTML', async () => {
    stubTransits(() =>
      Response.json({
        items: [{ ...item, vessel_name: '<img src=x onerror=alert(1)>' }],
        total: 1,
      }),
    );
    const { container } = renderWithQuery(
      <TransitsPanel token="abc" selectedMmsi={null} onSelect={vi.fn()} />,
    );

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeVisible();
    expect(container.querySelector('img')).toBeNull();
  });
});
