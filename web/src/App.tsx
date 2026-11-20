import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import './App.css';
import { ApiError } from './api/client';
import { LoginForm } from './auth/LoginForm';
import { useSession } from './auth/useSession';
import { config } from './config';
import { DemoBanner } from './demo/DemoBanner';
import { useDemoVessels } from './demo/useDemoVessels';
import type { Bbox, LiveVessel } from './live/protocol';
import { type LiveStatus, useLiveVessels } from './live/useLiveVessels';
import { MapLegend } from './map/MapLegend';
import { MapSidebar } from './map/MapSidebar';
import type { ShipCategory } from './map/vesselGeoJson';
import type { MapFocusTarget } from './map/VesselMap';
import { GuideDialog } from './onboarding/GuideDialog';
import { hasSeenGuide, rememberGuideSeen } from './onboarding/guideStorage';
import { StatsView } from './stats/StatsView';
import { useTransitDurations } from './stats/queries';
import {
  applyDocumentTheme,
  BASEMAP_STORAGE_KEY,
  type BasemapMode,
  readStoredBasemap,
  readStoredTheme,
  THEME_STORAGE_KEY,
  type ThemeMode,
  writeStorage,
} from './theme';
import { TransitsPanel } from './transits/TransitsPanel';
import { useCurrentTransits } from './transits/queries';
import { ConnectionDot } from './ui/ConnectionDot';
import { type AppView, readUrlState, writeUrlState } from './urlState';
import { fetchVesselDetail } from './vessels/api';
import { HeaderVesselSearch, type SearchCandidate } from './vessels/HeaderVesselSearch';
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
  const [selectedMmsi, setSelectedMmsi] = useState<number | null>(() => readUrlState().mmsi);
  const [view, setView] = useState<AppView>(() => readUrlState().view);
  const [guestDemo, setGuestDemo] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(readStoredTheme);
  const [basemap, setBasemap] = useState<BasemapMode>(readStoredBasemap);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [focusTarget, setFocusTarget] = useState<MapFocusTarget | null>(null);
  const [hiddenCategories, setHiddenCategories] = useState<ReadonlySet<ShipCategory>>(
    () => new Set(),
  );
  const [transitOnly, setTransitOnly] = useState(false);
  const mapTabRef = useRef<HTMLButtonElement>(null);
  const statsTabRef = useRef<HTMLButtonElement>(null);
  // Guía al primer uso (issue #137): sale sola hasta que se cierra una vez; luego, con el "?".
  const [guideOpen, setGuideOpen] = useState(() => !hasSeenGuide());
  const closeGuide = useCallback(() => {
    setGuideOpen(false);
    rememberGuideSeen();
  }, []);
  const isDemo = config.demo || guestDemo;
  // Un 4401 de `/ws/live` o un 401 de la API piden renovar el token; si la renovación dice que
  // ya no hay sesión, `useSession` pasa a `signedOut` con `expired` y se vuelve al login.
  const live = useLiveVessels(isDemo ? null : token, bbox, renew);
  const demo = useDemoVessels();
  const track = useVesselTrack(selectedMmsi, isDemo ? null : token);

  useEffect(() => {
    applyDocumentTheme(theme);
    writeStorage(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    writeStorage(BASEMAP_STORAGE_KEY, basemap);
  }, [basemap]);

  useEffect(() => {
    writeUrlState({ view: isDemo ? 'map' : view, mmsi: selectedMmsi });
  }, [isDemo, view, selectedMmsi]);

  useEffect(() => {
    const onPopState = () => {
      const next = readUrlState();
      setView(next.view);
      setSelectedMmsi(next.mmsi);
    };
    window.addEventListener('popstate', onPopState);
    return () => {
      window.removeEventListener('popstate', onPopState);
    };
  }, []);

  const closePanel = useCallback(() => {
    setSelectedMmsi(null);
  }, []);

  const handleSignOut = useCallback(() => {
    setGuestDemo(false);
    setSelectedMmsi(null);
    setView('map');
    session.signOut();
  }, [session]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  const toggleCategory = useCallback((category: ShipCategory) => {
    setHiddenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  }, []);

  // El panel de tránsitos no existe en la demo estática (ADR-0011): no hay API detrás. Estas
  // consultas comparten clave y caché con los paneles, así que no duplican peticiones.
  const transits = useCurrentTransits(isDemo ? null : token);
  const durations = useTransitDurations(isDemo ? null : token, 30);

  const transitMmsis = useMemo(
    () => new Set(transits.data?.items.map((item) => item.mmsi) ?? []),
    [transits.data],
  );
  const selectedTransit = useMemo(
    () =>
      selectedMmsi === null
        ? undefined
        : transits.data?.items.find((item) => item.mmsi === selectedMmsi),
    [selectedMmsi, transits.data],
  );

  const trackUnauthorized = track.error instanceof ApiError && track.error.status === 401;
  const transitsUnauthorized = transits.error instanceof ApiError && transits.error.status === 401;
  useEffect(() => {
    if ((trackUnauthorized || transitsUnauthorized) && token !== null && !isDemo) {
      renew(token);
    }
  }, [trackUnauthorized, transitsUnauthorized, token, isDemo, renew]);

  // En modo demo (build o invitado) se salta el login y se usan los buques pregrabados (ADR-0011).
  const activeVessels = isDemo ? demo : live;
  const mapReady = isDemo || (session.status === 'signedIn' && token !== null);
  const selectedLive = selectedMmsi === null ? undefined : activeVessels.vessels.get(selectedMmsi);

  const focusAndSelectVessel = useCallback((vessel: LiveVessel) => {
    setView('map');
    setSelectedMmsi(vessel.mmsi);
    setFocusTarget((prev) => ({ lon: vessel.lon, lat: vessel.lat, seq: (prev?.seq ?? 0) + 1 }));
  }, []);

  const selectFromSearch = useCallback(
    (candidate: SearchCandidate) => {
      setView('map');
      setSelectedMmsi(candidate.mmsi);
      const liveVessel = activeVessels.vessels.get(candidate.mmsi);
      if (liveVessel !== undefined) {
        setFocusTarget((prev) => ({
          lon: liveVessel.lon,
          lat: liveVessel.lat,
          seq: (prev?.seq ?? 0) + 1,
        }));
        return;
      }
      const { lon, lat } = candidate;
      if (lon !== null && lat !== null) {
        setFocusTarget((prev) => ({ lon, lat, seq: (prev?.seq ?? 0) + 1 }));
        return;
      }
      if (!isDemo && token !== null) {
        void fetchVesselDetail(candidate.mmsi, token)
          .then((detail) => {
            if (detail.last_position !== null) {
              const { lon, lat } = detail.last_position;
              setFocusTarget((prev) => ({ lon, lat, seq: (prev?.seq ?? 0) + 1 }));
            }
          })
          .catch(() => undefined);
      }
    },
    [activeVessels.vessels, isDemo, token],
  );

  const selectAndMaybeFocus = useCallback(
    (mmsi: number | null) => {
      setSelectedMmsi(mmsi);
      if (mmsi === null) {
        return;
      }
      const vessel = activeVessels.vessels.get(mmsi);
      if (vessel !== undefined) {
        setFocusTarget((prev) => ({ lon: vessel.lon, lat: vessel.lat, seq: (prev?.seq ?? 0) + 1 }));
      }
    },
    [activeVessels.vessels],
  );

  const handleTabKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowRight' || event.key === 'End') {
      event.preventDefault();
      setView('stats');
      statsTabRef.current?.focus();
    } else if (event.key === 'ArrowLeft' || event.key === 'Home') {
      event.preventDefault();
      setView('map');
      mapTabRef.current?.focus();
    }
  }, []);

  return (
    <main className="app">
      <header className="app__header">
        <div>
          <div className="app__brand">
            <span className="app__logo" aria-hidden="true">
              <svg viewBox="0 0 20 20" width="18" height="18">
                <path
                  d="M4.5 3.5v13M15.5 3.5v13"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  opacity="0.5"
                />
                <path
                  d="M5 7 10 4.8 15 7"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path d="M10 6.5 12.6 10.6v4.6L10 16.5l-2.6-1.3v-4.6L10 6.5Z" fill="currentColor" />
              </svg>
            </span>
            <h1>Panama Canal Tracker</h1>
            {mapReady && (
              <button
                type="button"
                className="app__help"
                aria-label="Cómo usar el tracker"
                aria-haspopup="dialog"
                onClick={() => {
                  setGuideOpen(true);
                }}
              >
                ?
              </button>
            )}
          </div>
          {isDemo ? (
            <p className="app__subtitle">Demo con datos simulados del Canal de Panamá.</p>
          ) : (
            <p className="app__subtitle">
              Buques del Canal de Panamá en tiempo real a partir de datos AIS.
            </p>
          )}
        </div>
        <div className="app__header-controls">
          {mapReady && (
            <HeaderVesselSearch
              vessels={activeVessels.vessels}
              token={token}
              demo={isDemo}
              onSelect={selectFromSearch}
            />
          )}
          {mapReady && !isDemo && (
            <nav className="app__tabs" aria-label="Vista">
              <div
                role="tablist"
                aria-label="Vistas"
                className="app__tablist"
                onKeyDown={handleTabKeyDown}
              >
                <button
                  ref={mapTabRef}
                  type="button"
                  role="tab"
                  aria-selected={view === 'map'}
                  tabIndex={view === 'map' ? 0 : -1}
                  onClick={() => {
                    setView('map');
                  }}
                >
                  <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                    <path
                      d="M2 3.8 5.8 2l4.4 1.8L14 2v10.2L10.2 14l-4.4-1.8L2 14V3.8Z"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M5.8 2v10.2M10.2 3.8V14"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.4"
                    />
                  </svg>
                  <span>Mapa</span>
                </button>
                <button
                  ref={statsTabRef}
                  type="button"
                  role="tab"
                  aria-selected={view === 'stats'}
                  tabIndex={view === 'stats' ? 0 : -1}
                  onClick={() => {
                    setView('stats');
                  }}
                >
                  <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                    <path
                      d="M2.5 13.5h11M4.5 11V7.5M8 11V4.5M11.5 11V6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                  </svg>
                  <span>Estadísticas</span>
                </button>
              </div>
            </nav>
          )}
          {mapReady && (
            <p className="app__status" role="status">
              {!isDemo && <ConnectionDot status={live.status} />}
              {isDemo ? 'Demo' : STATUS_TEXT[live.status]} · {activeVessels.vessels.size} buques
            </p>
          )}
          <button
            type="button"
            className="app__theme"
            aria-label={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
            aria-pressed={theme === 'dark'}
            title={theme === 'dark' ? 'Tema claro' : 'Tema oscuro'}
            onClick={toggleTheme}
          >
            {theme === 'dark' ? (
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <circle
                  cx="8"
                  cy="8"
                  r="3.25"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                />
                <path
                  d="M8 1.5v1.4M8 13.1v1.4M1.5 8h1.4M13.1 8h1.4M3.4 3.4l1 1M11.6 11.6l1 1M12.6 3.4l-1 1M4.4 11.6l-1 1"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            ) : (
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path
                  d="M12.9 10.2A5.5 5.5 0 0 1 5.8 3.1a5.75 5.75 0 1 0 7.1 7.1Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinejoin="round"
                />
              </svg>
            )}
            <span>{theme === 'dark' ? 'Claro' : 'Oscuro'}</span>
          </button>
          {mapReady && !isDemo && (
            <button
              type="button"
              className="app__logout"
              aria-label="Cerrar sesión"
              onClick={handleSignOut}
            >
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path
                  d="M6.5 2.5h-3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3M10.5 5l3 3-3 3M13.5 8H6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span>Salir</span>
            </button>
          )}
        </div>
      </header>
      {isDemo && (
        <DemoBanner
          onExit={
            guestDemo
              ? () => {
                  setGuestDemo(false);
                  setSelectedMmsi(null);
                  setView('map');
                }
              : undefined
          }
        />
      )}
      {/* Nunca encima del login: solo cuando ya se ve el mapa. */}
      <GuideDialog open={mapReady && guideOpen} demo={isDemo} onClose={closeGuide} />
      {view === 'stats' && !isDemo && token !== null ? (
        <StatsView token={token} onUnauthorized={renew} />
      ) : (
        <section className="app__map" aria-label="Mapa en vivo">
          {mapReady ? (
            <div className={sidebarCollapsed ? 'workspace workspace--collapsed' : 'workspace'}>
              <MapSidebar
                vessels={activeVessels.vessels}
                selectedMmsi={selectedMmsi}
                onSelectVessel={focusAndSelectVessel}
                onClearSelection={closePanel}
                demo={isDemo}
                transitsCount={transits.data?.total ?? null}
                collapsed={sidebarCollapsed}
                onToggleCollapse={() => {
                  setSidebarCollapsed((prev) => !prev);
                }}
                detailSlot={
                  selectedMmsi !== null && !isDemo && token !== null ? (
                    <VesselPanel
                      key={selectedMmsi}
                      mmsi={selectedMmsi}
                      token={token}
                      live={selectedLive}
                      currentTransit={selectedTransit}
                      onClose={closePanel}
                    />
                  ) : null
                }
                transitsSlot={
                  !isDemo && token !== null ? (
                    <TransitsPanel
                      token={token}
                      selectedMmsi={selectedMmsi}
                      onSelect={selectAndMaybeFocus}
                      medianMinutes={durations.data?.overall.p50_minutes ?? null}
                    />
                  ) : null
                }
              />
              <div className="workspace__stage">
                <Suspense
                  fallback={
                    <div className="app__splash">
                      <span className="app__spinner" aria-hidden="true" />
                      <p>Cargando el mapa…</p>
                    </div>
                  }
                >
                  <VesselMap
                    vessels={activeVessels.vessels}
                    onViewportChange={setBbox}
                    selectedMmsi={selectedMmsi}
                    onSelect={setSelectedMmsi}
                    trail={selectedMmsi === null ? null : trailFeature(track.data, selectedLive)}
                    basemap={basemap}
                    theme={theme}
                    focusTarget={focusTarget}
                    mapFilter={{ hiddenCategories, transitOnly, transitMmsis }}
                  />
                </Suspense>
                <div className="map-toolbar">
                  {sidebarCollapsed && (
                    <button
                      type="button"
                      className="map-toolbar__expand"
                      aria-label="Mostrar panel lateral"
                      onClick={() => {
                        setSidebarCollapsed(false);
                      }}
                    >
                      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                        <path
                          d="M6 3.5 10.5 8 6 12.5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.75"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                      <span>Panel</span>
                    </button>
                  )}
                  <div className="basemap-switch" role="group" aria-label="Capa base del mapa">
                    <button
                      type="button"
                      aria-pressed={basemap === 'map'}
                      onClick={() => {
                        setBasemap('map');
                      }}
                    >
                      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                        <path
                          d="M2 3.8 5.8 2l4.4 1.8L14 2v10.2L10.2 14l-4.4-1.8L2 14V3.8Z"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinejoin="round"
                        />
                      </svg>
                      <span>Estándar</span>
                    </button>
                    <button
                      type="button"
                      aria-pressed={basemap === 'satellite'}
                      onClick={() => {
                        setBasemap('satellite');
                      }}
                    >
                      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                        <path
                          d="M8 2.5 14 5.8 8 9 2 5.8 8 2.5Zm-6 5.6 6 3.2 6-3.2M2 10.7l6 3.2 6-3.2"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                      <span>Satélite</span>
                    </button>
                  </div>
                </div>
                <MapLegend
                  hiddenCategories={hiddenCategories}
                  onToggleCategory={toggleCategory}
                  transitOnly={transitOnly}
                  onToggleTransitOnly={() => {
                    setTransitOnly((prev) => !prev);
                  }}
                  showTransitFilter={!isDemo && token !== null}
                />
              </div>
            </div>
          ) : session.status === 'restoring' ? (
            <div className="app__splash">
              <span className="app__spinner" aria-hidden="true" />
              <p>Recuperando la sesión…</p>
            </div>
          ) : (
            <LoginForm
              onLogin={session.signIn}
              notice={session.expired ? EXPIRED_NOTICE : undefined}
              onTryDemo={
                config.demo
                  ? undefined
                  : () => {
                      setGuestDemo(true);
                    }
              }
            />
          )}
        </section>
      )}
    </main>
  );
}
