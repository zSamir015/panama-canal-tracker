import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { login, LoginError, register } from './login';
import { LoginForm } from './LoginForm';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('login', () => {
  it('envía las credenciales con la cookie y devuelve la sesión', async () => {
    const fetchImpl = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        jsonResponse(200, { access_token: 'abc', token_type: 'bearer', expires_in: 900 }),
      ),
    );
    const before = Date.now();

    const session = await login('demo@example.com', 'changeme-changeme', fetchImpl);

    expect(session.accessToken).toBe('abc');
    expect(session.expiresAt).toBeGreaterThanOrEqual(before + 900_000);

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

describe('register', () => {
  it('crea la cuenta y entra automáticamente', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(201, { id: 'u1', email: 'demo@example.com' }))
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'nuevo', token_type: 'bearer', expires_in: 900 }),
      );

    const session = await register('demo@example.com', 'changeme-changeme', fetchImpl);

    expect(session.accessToken).toBe('nuevo');
    expect(fetchImpl.mock.calls[0]?.[0]).toBe('/api/v1/auth/register');
    expect(fetchImpl.mock.calls[1]?.[0]).toBe('/api/v1/auth/login');
  });

  it.each([
    [409, 'ya está registrado'],
    [422, 'mínimo 12 caracteres'],
    [429, 'Demasiados intentos'],
    [500, 'No se pudo crear la cuenta'],
  ])('traduce el %s al registrar', async (status, message) => {
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(status, {})));

    await expect(register('a@example.com', 'changeme-changeme', fetchImpl)).rejects.toThrow(
      message,
    );
  });
});

describe('LoginForm', () => {
  it('entrega la sesión al iniciar sesión', async () => {
    const onLogin = vi.fn();
    const session = { accessToken: 'abc', expiresAt: 0 };
    const loginImpl = vi.fn(() => Promise.resolve(session));
    render(<LoginForm onLogin={onLogin} loginImpl={loginImpl} />);

    await userEvent.type(screen.getByLabelText('Email'), 'demo@example.com');
    await userEvent.type(screen.getByLabelText('Contraseña'), 'changeme-changeme');
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(loginImpl).toHaveBeenCalledWith('demo@example.com', 'changeme-changeme');
    expect(onLogin).toHaveBeenCalledWith(session);
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

  it('permite cambiar al modo de creación de cuenta y registra', async () => {
    const onLogin = vi.fn();
    const session = { accessToken: 'reg', expiresAt: 0 };
    const registerImpl = vi.fn(() => Promise.resolve(session));
    render(<LoginForm onLogin={onLogin} registerImpl={registerImpl} />);

    await userEvent.click(screen.getByRole('button', { name: /Crear cuenta/ }));
    expect(screen.getByRole('heading', { name: 'Crear cuenta' })).toBeVisible();
    expect(screen.getByText('Entre 12 y 128 caracteres.')).toBeVisible();

    await userEvent.type(screen.getByLabelText('Email'), 'nuevo@example.com');
    await userEvent.type(screen.getByLabelText('Contraseña'), 'una-frase-larga-123');
    await userEvent.click(screen.getByRole('button', { name: 'Crear cuenta' }));

    expect(registerImpl).toHaveBeenCalledWith('nuevo@example.com', 'una-frase-larga-123');
    expect(onLogin).toHaveBeenCalledWith(session);
  });

  it('permite mostrar u ocultar la contraseña y abrir la demo sin cuenta', async () => {
    const onTryDemo = vi.fn();
    render(<LoginForm onLogin={vi.fn()} onTryDemo={onTryDemo} />);

    const passwordInput = screen.getByLabelText('Contraseña');
    expect(passwordInput).toHaveAttribute('type', 'password');

    const toggle = screen.getByRole('button', { name: 'Mostrar contraseña' });
    await userEvent.click(toggle);
    expect(passwordInput).toHaveAttribute('type', 'text');
    expect(screen.getByRole('button', { name: 'Ocultar contraseña' })).toBeVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Ver demo sin cuenta' }));
    expect(onTryDemo).toHaveBeenCalledTimes(1);
  });
});
