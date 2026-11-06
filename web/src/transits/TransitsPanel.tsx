import { useEffect, useState } from 'react';
import type { CurrentTransit } from './api';
import { directionText, elapsedText, transitName } from './format';
import { useCurrentTransits } from './queries';

interface TransitsPanelProps {
  token: string;
  selectedMmsi: number | null;
  onSelect: (mmsi: number) => void;
}

/**
 * "En tránsito ahora": los buques que entraron por una entrada del Canal y aún no han salido por
 * la otra. Nombres y demás datos vienen de AIS: se pintan como texto con React, nunca como HTML
 * (AGENTS.md §8.7).
 */
export function TransitsPanel({ token, selectedMmsi, onSelect }: TransitsPanelProps) {
  const transits = useCurrentTransits(token);
  const now = useNow(30_000);
  const data = transits.data;

  return (
    <aside className="transits-panel" aria-label="En tránsito ahora">
      <h2>
        En tránsito ahora
        {data !== undefined && (
          <>
            {' '}
            <span className="transits-panel__count">({data.total})</span>
          </>
        )}
      </h2>
      {transits.isPending && <p>Cargando…</p>}
      {transits.isError && (
        <p className="transits-panel__error" role="alert">
          {transits.error.message}
        </p>
      )}
      {data?.items.length === 0 && (
        <p className="transits-panel__empty">Ningún buque en tránsito.</p>
      )}
      {data !== undefined && data.items.length > 0 && (
        <ul>
          {data.items.map((transit) => (
            <TransitRow
              key={transit.id}
              transit={transit}
              now={now}
              selected={transit.mmsi === selectedMmsi}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
      {data !== undefined && data.total > data.items.length && (
        <p className="transits-panel__note">
          Se muestran {data.items.length} de {data.total}.
        </p>
      )}
    </aside>
  );
}

interface TransitRowProps {
  transit: CurrentTransit;
  now: number;
  selected: boolean;
  onSelect: (mmsi: number) => void;
}

function TransitRow({ transit, now, selected, onSelect }: TransitRowProps) {
  return (
    <li>
      <button
        type="button"
        className="transits-panel__row"
        aria-pressed={selected}
        onClick={() => {
          onSelect(transit.mmsi);
        }}
      >
        <span className="transits-panel__name">
          {transitName(transit.vessel_name, transit.mmsi)}
        </span>
        <span className="transits-panel__detail">
          {directionText(transit.direction)} · {elapsedText(transit.entered_at, now)}
        </span>
      </button>
    </li>
  );
}

/** La hora actual, refrescada cada `intervalMs` para que "lleva X" avance solo. */
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
