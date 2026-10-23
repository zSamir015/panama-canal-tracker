import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { login, LoginError } from './login';
import { LoginForm } from './LoginForm';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('login', () => {
  it('envía las credenciales con la cookie y devuelve el access token', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(200, { access_token: 'abc', token_type: 'bearer' })),
    );

    await expect(login('demo@example.com', 'changeme-changeme', fetchImpl)).resolves.toBe('abc');

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/auth/login');
    expect(init).toMatchObject({ method: 'POST', credentials: 'include' });
    expect(JSON.parse(init?.body as string)).toEqual({
      email: 'demo@example.com',
      password: 'changeme-changeme',
    });
  });

  it.each([
    [401, 'incorrectos'],
    [429, 'Demasiados intentos'],
    [500, 'No se pudo iniciar sesión'],
  ])('traduce el %s a un mensaje', async (status, message) => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(status, {})));

    await expect(login('a@example.com', 'x', fetchImpl)).rejects.toThrow(message);
  });

  it('falla si la red no responde o la respuesta no trae token', async () => {
    await expect(
      login('a@example.com', 'x', () => Promise.reject(new TypeError())),
    ).rejects.toThrow(LoginError);
    await expect(
      login('a@example.com', 'x', () => Promise.resolve(jsonResponse(200, {}))),
    ).rejects.toThrow('inesperada');
  });
});

describe('LoginForm', () => {
  it('entrega el token al iniciar sesión', async () => {
    const onLogin = vi.fn();
    const loginImpl = vi.fn(() => Promise.resolve('abc'));
    render(<LoginForm onLogin={onLogin} loginImpl={loginImpl} />);

    await userEvent.type(screen.getByLabelText('Email'), 'demo@example.com');
    await userEvent.type(screen.getByLabelText('Contraseña'), 'changeme-changeme');
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(loginImpl).toHaveBeenCalledWith('demo@example.com', 'changeme-changeme');
    expect(onLogin).toHaveBeenCalledWith('abc');
  });

  it('muestra el error como texto y deja reintentar', async () => {
    const loginImpl = vi.fn(() =>
      Promise.reject(new LoginError('Email o contraseña incorrectos.')),
    );
    render(<LoginForm onLogin={vi.fn()} loginImpl={loginImpl} />);

    await userEvent.type(screen.getByLabelText('Email'), 'demo@example.com');
    await userEvent.type(screen.getByLabelText('Contraseña'), 'mala');
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Email o contraseña incorrectos.');
    expect(screen.getByRole('button', { name: 'Entrar' })).toBeEnabled();
  });
});
