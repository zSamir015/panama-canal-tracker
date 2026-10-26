import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import './App.css';
import { ApiError } from './api/client';
import { LoginForm } from './auth/LoginForm';
import { useSession } from './auth/useSession';
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
  reconnecting: 'Reconectando…',
  closed: 'Desconectado',
};

const EXPIRED_NOTICE = 'La sesión caducó. Vuelve a iniciar sesión.';

export function App() {
  const session = useSession();
  const { token, renew } = session;
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<number | null>(null);
  // Un 4401 de `/ws/live` o un 401 de la API piden renovar el token; si la renovación dice que
  // ya no hay sesión, `useSession` pasa a `signedOut` con `expired` y se vuelve al login.
  const live = useLiveVessels(token, bbox, renew);
  const track = useVesselTrack(selectedMmsi, token);

  const closePanel = useCallback(() => {
    setSelectedMmsi(null);
  }, []);

  const trackUnauthorized = track.error instanceof ApiError && track.error.status === 401;
  useEffect(() => {
    if (trackUnauthorized && token !== null) {
      renew(token);
    }
  }, [trackUnauthorized, token, renew]);

  const signedIn = session.status === 'signedIn' && token !== null;
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
        ) : session.status === 'restoring' ? (
          <p>Recuperando la sesión…</p>
        ) : (
          <LoginForm
            onLogin={session.signIn}
            notice={session.expired ? EXPIRED_NOTICE : undefined}
          />
        )}
      </section>
    </main>
  );
}
