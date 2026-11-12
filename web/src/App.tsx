import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import './App.css';
import { ApiError } from './api/client';
import { LoginForm } from './auth/LoginForm';
import { useSession } from './auth/useSession';
import { config } from './config';
import { DemoBanner } from './demo/DemoBanner';
import { useDemoVessels } from './demo/useDemoVessels';
import type { Bbox } from './live/protocol';
import { type LiveStatus, useLiveVessels } from './live/useLiveVessels';
import { MapLegend } from './map/MapLegend';
import { StatsView } from './stats/StatsView';
import { TransitsPanel } from './transits/TransitsPanel';
import { useCurrentTransits } from './transits/queries';
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
  const [view, setView] = useState<'map' | 'stats'>('map');
  // Un 4401 de `/ws/live` o un 401 de la API piden renovar el token; si la renovación dice que
  // ya no hay sesión, `useSession` pasa a `signedOut` con `expired` y se vuelve al login.
  const live = useLiveVessels(token, bbox, renew);
  const demo = useDemoVessels();
  const track = useVesselTrack(selectedMmsi, token);

  const closePanel = useCallback(() => {
    setSelectedMmsi(null);
  }, []);

  // El panel de tránsitos no existe en la demo estática (ADR-0011): no hay API detrás. Esta
  // consulta comparte clave y caché con la del panel, así que no duplica la petición.
  const transits = useCurrentTransits(config.demo ? null : token);

  const trackUnauthorized = track.error instanceof ApiError && track.error.status === 401;
  const transitsUnauthorized = transits.error instanceof ApiError && transits.error.status === 401;
  useEffect(() => {
    if ((trackUnauthorized || transitsUnauthorized) && token !== null) {
      renew(token);
    }
  }, [trackUnauthorized, transitsUnauthorized, token, renew]);

  // En modo demo se salta el login y se usan los buques pregrabados (ADR-0011).
  const activeVessels = config.demo ? demo : live;
  const mapReady = config.demo || (session.status === 'signedIn' && token !== null);
  const selectedLive = selectedMmsi === null ? undefined : activeVessels.vessels.get(selectedMmsi);

  return (
    <main className="app">
      <header className="app__header">
        <div>
          <h1>Panama Canal Tracker</h1>
          {config.demo ? (
            <p className="app__subtitle">Demo con datos simulados del Canal de Panamá.</p>
          ) : (
            <p className="app__subtitle">
              Buques del Canal de Panamá en tiempo real a partir de datos AIS.
            </p>
          )}
        </div>
        {mapReady && !config.demo && (
          <nav className="app__tabs" aria-label="Vista">
            <button
              type="button"
              aria-pressed={view === 'map'}
              onClick={() => {
                setView('map');
              }}
            >
              Mapa
            </button>
            <button
              type="button"
              aria-pressed={view === 'stats'}
              onClick={() => {
                setView('stats');
              }}
            >
              Estadísticas
            </button>
          </nav>
        )}
        {mapReady && (
          <p className="app__status" role="status">
            {config.demo ? 'Demo' : STATUS_TEXT[live.status]} · {activeVessels.vessels.size} buques
          </p>
        )}
      </header>
      {config.demo && <DemoBanner />}
      {view === 'stats' && !config.demo && token !== null ? (
        <StatsView token={token} onUnauthorized={renew} />
      ) : (
        <section className="app__map" aria-label="Mapa en vivo">
          {mapReady ? (
            <>
              <Suspense fallback={<p>Cargando el mapa…</p>}>
                <VesselMap
                  vessels={activeVessels.vessels}
                  onViewportChange={setBbox}
                  selectedMmsi={selectedMmsi}
                  onSelect={setSelectedMmsi}
                  trail={selectedMmsi === null ? null : trailFeature(track.data, selectedLive)}
                />
              </Suspense>
              <MapLegend />
              {!config.demo && token !== null && (
                <TransitsPanel
                  token={token}
                  selectedMmsi={selectedMmsi}
                  onSelect={setSelectedMmsi}
                />
              )}
              {selectedMmsi !== null && !config.demo && token !== null && (
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
      )}
    </main>
  );
}
