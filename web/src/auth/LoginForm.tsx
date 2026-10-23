import { type SubmitEvent, useState } from 'react';
import { login, LoginError } from './login';

interface LoginFormProps {
  onLogin: (accessToken: string) => void;
  /** Aviso a mostrar encima del formulario, p. ej. cuando la sesión caducó. */
  notice?: string | undefined;
  loginImpl?: typeof login;
}

/** Los datos de AISStream solo se muestran con sesión iniciada (ADR-0008). */
export function LoginForm({ onLogin, notice, loginImpl = login }: LoginFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      onLogin(await loginImpl(textField(form, 'email'), textField(form, 'password')));
    } catch (caught) {
      setError(caught instanceof LoginError ? caught.message : 'No se pudo iniciar sesión.');
      setPending(false);
    }
  }

  return (
    <form className="login" onSubmit={(event) => void handleSubmit(event)}>
      <h2>Iniciar sesión</h2>
      <p>El mapa en vivo necesita una cuenta: los datos AIS no se muestran de forma anónima.</p>
      {notice && <p className="login__notice">{notice}</p>}
      <label>
        Email
        <input name="email" type="email" autoComplete="username" required maxLength={320} />
      </label>
      <label>
        Contraseña
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
        />
      </label>
      {error && (
        <p className="login__error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" disabled={pending}>
        {pending ? 'Entrando…' : 'Entrar'}
      </button>
    </form>
  );
}

function textField(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === 'string' ? value : '';
}
