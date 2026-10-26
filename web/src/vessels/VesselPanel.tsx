import { useEffect, useState } from 'react';
import type { LiveVessel } from '../live/protocol';
import {
  agoText,
  courseText,
  dimensionsText,
  navStatusText,
  shipTypeText,
  speedText,
} from './format';
import { useVesselDetail } from './queries';

interface VesselPanelProps {
  mmsi: number;
  token: string;
  /** Última posición recibida por `/ws/live`; manda sobre la de la ficha, que es más vieja. */
  live: LiveVessel | undefined;
  onClose: () => void;
}

/**
 * Ficha del buque seleccionado. Todo lo que viene de AIS (nombre incluido) se pinta como texto con
 * React, nunca como HTML (AGENTS.md §8.7).
 */
export function VesselPanel({ mmsi, token, live, onClose }: VesselPanelProps) {
  const detail = useVesselDetail(mmsi, token);
  const now = useNow(5000);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const data = detail.data;
  const position = data?.last_position;
  const name = live?.name ?? data?.name ?? null;

  return (
    <aside className="vessel-panel" aria-label="Ficha del buque">
      <header className="vessel-panel__header">
        <h2>{displayName(name)}</h2>
        <button type="button" onClick={onClose} aria-label="Cerrar la ficha">
          ×
        </button>
      </header>
      {detail.isPending && <p>Cargando…</p>}
      {detail.isError && (
        <p className="vessel-panel__error" role="alert">
          {detail.error.message}
        </p>
      )}
      <dl>
        <dt>MMSI</dt>
        <dd>{mmsi}</dd>
        <dt>IMO</dt>
        <dd>{data?.imo ?? '—'}</dd>
        <dt>Tipo</dt>
        <dd>{shipTypeText(live?.ship_type ?? data?.ship_type ?? null)}</dd>
        <dt>Eslora × manga</dt>
        <dd>{dimensionsText(data?.length_m ?? null, data?.beam_m ?? null)}</dd>
        <dt>Velocidad</dt>
        <dd>{speedText(live?.sog ?? position?.sog ?? null)}</dd>
        <dt>Rumbo</dt>
        <dd>{courseText(live?.cog ?? position?.cog ?? null)}</dd>
        <dt>Estado</dt>
        <dd>{navStatusText(position?.nav_status ?? null)}</dd>
        <dt>Última señal</dt>
        <dd>{agoText(live?.ts ?? position?.received_at ?? null, now)}</dd>
      </dl>
      <p className="vessel-panel__note">Estela: últimos 30 minutos.</p>
    </aside>
  );
}

/** La hora actual, refrescada cada `intervalMs` para que "hace X" avance solo. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}

function displayName(name: string | null): string {
  const trimmed = name?.trim();
  // AIS rellena con espacios: un nombre en blanco es lo mismo que no tenerlo.
  return trimmed === undefined || trimmed === '' ? 'Sin nombre' : trimmed;
}
