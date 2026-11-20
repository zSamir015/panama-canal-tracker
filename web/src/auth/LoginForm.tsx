import { type SubmitEvent, useId, useState } from 'react';
import { login, LoginError, register } from './login';
import type { Session } from './session';

type AuthMode = 'login' | 'register';

interface LoginFormProps {
  onLogin: (session: Session) => void;
  /** Aviso a mostrar encima del formulario, p. ej. cuando la sesión caducó. */
  notice?: string | undefined;
  /** Acceso opcional a la demo simulada sin iniciar sesión (portafolio / revisión). */
  onTryDemo?: (() => void) | undefined;
  loginImpl?: typeof login;
  registerImpl?: typeof register;
}

/** Los datos de AISStream solo se muestran con sesión iniciada (ADR-0008). */
export function LoginForm({
  onLogin,
  notice,
  onTryDemo,
  loginImpl = login,
  registerImpl = register,
}: LoginFormProps) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [showPassword, setShowPassword] = useState(false);
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
          <span className="login__password-wrap">
            <input
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              minLength={isRegister ? 12 : undefined}
              maxLength={128}
              aria-describedby={isRegister ? hintId : undefined}
            />
            <button
              type="button"
              className="login__password-toggle"
              aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
              aria-pressed={showPassword}
              onClick={() => {
                setShowPassword((prev) => !prev);
              }}
            >
              {showPassword ? (
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                  <path
                    d="M2.2 2.2 13.8 13.8M6.5 6.5a2 2 0 0 0 2.8 2.8M1.5 8s2.4-4 6.5-4c1.1 0 2.1.3 3 .8M14.5 8s-1.2 2-3.2 3.1"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                  />
                </svg>
              ) : (
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                  <path
                    d="M1.5 8S4 4 8 4s6.5 4 6.5 4-2.5 4-6.5 4S1.5 8 1.5 8Z"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinejoin="round"
                  />
                  <circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" strokeWidth="1.4" />
                </svg>
              )}
            </button>
          </span>
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
      {onTryDemo !== undefined && (
        <p className="login__demo">
          <button type="button" className="login__demo-link" onClick={onTryDemo} disabled={pending}>
            Ver demo sin cuenta
          </button>
        </p>
      )}
    </form>
  );
}

function textField(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === 'string' ? value : '';
}
