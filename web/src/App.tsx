import { lazy, Suspense, useCallback, useState } from 'react';
import './App.css';
import { ApiError } from './api/client';
import { LoginForm } from './auth/LoginForm';
import type { Bbox } from './live/protocol';
import { type LiveStatus, useLiveVessels } from './live/useLiveVessels';
import { MapLegend } from './map/MapLegend';
import { useVesselTrack } from './vessels/queries';
import { trailFeature } from './vessels/trail';
import { VesselPanel } from './vessels/VesselPanel';

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
const EXPIRED_NOTICE = 'La sesión caducó. Vuelve a iniciar sesión.';

export function App() {
  // El access token vive solo en memoria (AGENTS.md §8.4): recargar la página pide entrar otra vez
  // hasta que la 4.5 renueve la sesión con el refresh token.
  const [token, setToken] = useState<string | null>(null);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<number | null>(null);
  const live = useLiveVessels(token, bbox);
  const track = useVesselTrack(selectedMmsi, token);

  const closePanel = useCallback(() => {
    setSelectedMmsi(null);
  }, []);

  // El token caducó si lo rechaza `/ws/live` (cierre 4401) o la API REST (401 en la estela).
  // Ambos estados van ligados al token: con uno nuevo, vuelven a empezar de cero.
  const expired =
    live.closeCode === UNAUTHORIZED_CLOSE_CODE ||
    (track.error instanceof ApiError && track.error.status === 401);
  const signedIn = token !== null && !expired;
  const selectedLive = selectedMmsi === null ? undefined : live.vessels.get(selectedMmsi);

  return (
    <main className="app">
      <header className="app__header">
        <div>
          <h1>Panama Canal Tracker</h1>
          <p>Buques del Canal de Panamá en tiempo real a partir de datos AIS.</p>
        </div>
        {signedIn && (
          <p className="app__status" role="status">
            {STATUS_TEXT[live.status]} · {live.vessels.size} buques
          </p>
        )}
      </header>
      <section className="app__map" aria-label="Mapa en vivo">
        {signedIn ? (
          <>
            <Suspense fallback={<p>Cargando el mapa…</p>}>
              <VesselMap
                vessels={live.vessels}
                onViewportChange={setBbox}
                selectedMmsi={selectedMmsi}
                onSelect={setSelectedMmsi}
                trail={selectedMmsi === null ? null : trailFeature(track.data, selectedLive)}
              />
            </Suspense>
            <MapLegend />
            {selectedMmsi !== null && (
              <VesselPanel
                key={selectedMmsi}
                mmsi={selectedMmsi}
                token={token}
                live={selectedLive}
                onClose={closePanel}
              />
            )}
          </>
        ) : (
          <LoginForm onLogin={setToken} notice={expired ? EXPIRED_NOTICE : undefined} />
        )}
      </section>
    </main>
  );
}
