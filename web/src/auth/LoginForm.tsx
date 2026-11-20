import { type SubmitEvent, useId, useState } from 'react';
import { login, LoginError, register } from './login';
import type { Session } from './session';

type AuthMode = 'login' | 'register';

interface LoginFormProps {
  onLogin: (session: Session) => void;
  /** Aviso a mostrar encima del formulario, p. ej. cuando la sesión caducó. */
  notice?: string | undefined;
  loginImpl?: typeof login;
  registerImpl?: typeof register;
}

/** Los datos de AISStream solo se muestran con sesión iniciada (ADR-0008). */
export function LoginForm({
  onLogin,
  notice,
  loginImpl = login,
  registerImpl = register,
}: LoginFormProps) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const hintId = useId();
  const isRegister = mode === 'register';

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    const submit = isRegister ? registerImpl : loginImpl;
    try {
      onLogin(await submit(textField(form, 'email'), textField(form, 'password')));
    } catch (caught) {
      const fallback = isRegister ? 'No se pudo crear la cuenta.' : 'No se pudo iniciar sesión.';
      setError(caught instanceof LoginError ? caught.message : fallback);
      setPending(false);
    }
  }

  function switchMode() {
    setMode((current) => (current === 'login' ? 'register' : 'login'));
    setError(null);
  }

  return (
    <form className="login" onSubmit={(event) => void handleSubmit(event)}>
      <h2>{isRegister ? 'Crear cuenta' : 'Iniciar sesión'}</h2>
      <p className="login__intro">
        El mapa en vivo necesita una cuenta: los datos AIS no se muestran de forma anónima.
      </p>
      {notice && !isRegister && <p className="login__notice">{notice}</p>}
      <label>
        Email
        <input name="email" type="email" autoComplete="username" required maxLength={320} />
      </label>
      <div className="login__field">
        <label>
          Contraseña
          <input
            name="password"
            type="password"
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            required
            minLength={isRegister ? 12 : undefined}
            maxLength={128}
            aria-describedby={isRegister ? hintId : undefined}
          />
        </label>
        {isRegister && (
          <p id={hintId} className="login__hint">
            Entre 12 y 128 caracteres.
          </p>
        )}
      </div>
      {error && (
        <p className="login__error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="login__submit" disabled={pending}>
        {pending
          ? isRegister
            ? 'Creando cuenta…'
            : 'Entrando…'
          : isRegister
            ? 'Crear cuenta'
            : 'Entrar'}
      </button>
      <p className="login__footer">
        <button type="button" className="login__switch" onClick={switchMode} disabled={pending}>
          {isRegister ? '¿Ya tienes cuenta? Iniciar sesión' : '¿No tienes cuenta? Crear cuenta'}
        </button>
      </p>
    </form>
  );
}

function textField(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === 'string' ? value : '';
}
