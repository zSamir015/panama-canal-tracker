import { lazy, Suspense, useState } from 'react';
import './App.css';
import { LoginForm } from './auth/LoginForm';
import type { Bbox } from './live/protocol';
import { type LiveStatus, useLiveVessels } from './live/useLiveVessels';
import { MapLegend } from './map/MapLegend';

// MapLibre pesa ~1 MB: se descarga después de iniciar sesión, no con la pantalla de login.
const VesselMap = lazy(() =>
  import('./map/VesselMap').then((module) => ({ default: module.VesselMap })),
);

const STATUS_TEXT: Record<LiveStatus, string> = {
  idle: 'Sin conexión',
  connecting: 'Conectando…',
  live: 'En vivo',
  closed: 'Desconectado',
};

/** `4401`: el servidor rechazó el token (caducado o inválido); hay que volver a entrar. */
const UNAUTHORIZED_CLOSE_CODE = 4401;

export function App() {
  // El access token vive solo en memoria (AGENTS.md §8.4): recargar la página pide entrar otra vez
  // hasta que la 4.5 renueve la sesión con el refresh token.
  const [token, setToken] = useState<string | null>(null);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const live = useLiveVessels(token, bbox);
  const sessionExpired = live.closeCode === UNAUTHORIZED_CLOSE_CODE;

  return (
    <main className="app">
      <header className="app__header">
        <div>
          <h1>Panama Canal Tracker</h1>
          <p>Buques del Canal de Panamá en tiempo real a partir de datos AIS.</p>
        </div>
        {token && !sessionExpired && (
          <p className="app__status" role="status">
            {STATUS_TEXT[live.status]} · {live.vessels.size} buques
          </p>
        )}
      </header>
      <section className="app__map" aria-label="Mapa en vivo">
        {token && !sessionExpired ? (
          <>
            <Suspense fallback={<p>Cargando el mapa…</p>}>
              <VesselMap vessels={live.vessels} onViewportChange={setBbox} />
            </Suspense>
            <MapLegend />
          </>
        ) : (
          <LoginForm
            onLogin={setToken}
            notice={sessionExpired ? 'La sesión caducó. Vuelve a iniciar sesión.' : undefined}
          />
        )}
      </section>
    </main>
  );
}
