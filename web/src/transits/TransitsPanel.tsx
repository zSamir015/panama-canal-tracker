import { useEffect, useId, useRef, useState } from 'react';
import type { CurrentTransit } from './api';
import { directionText, elapsedText, transitName, transitProgress } from './format';
import { useCurrentTransits } from './queries';
import { friendlyError } from '../ui/errors';
import { Skeleton } from '../ui/Skeleton';
import { useSheetDrag } from '../ui/useSheetDrag';

interface TransitsPanelProps {
  token: string;
  selectedMmsi: number | null;
  onSelect: (mmsi: number) => void;
  /** Mediana histórica en minutos para estimar progreso y hora de salida. */
  medianMinutes?: number | null | undefined;
}

/**
 * "En tránsito ahora": los buques que entraron por una entrada del Canal y aún no han salido por
 * la otra. Nombres y demás datos vienen de AIS: se pintan como texto con React, nunca como HTML
 * (AGENTS.md §8.7).
 *
 * En móvil es una barra al pie del mapa que se despliega o se arrastra como hoja inferior; en
 * escritorio el CSS oculta el asa y la lista se ve siempre (issue #123).
 */
export function TransitsPanel({
  token,
  selectedMmsi,
  onSelect,
  medianMinutes,
}: TransitsPanelProps) {
  const transits = useCurrentTransits(token);
  const now = useNow(30_000);
  const data = transits.data;
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();
  const sheetDrag = useSheetDrag({
    onDismiss: () => {
      setExpanded(false);
    },
  });
  const suppressClickRef = useRef(false);

  // Al elegir un buque se pliega: en móvil su ficha ocupa la hoja inferior.
  const select = (mmsi: number) => {
    setExpanded(false);
    sheetDrag.resetTall();
    onSelect(mmsi);
  };

  const isExpanded = expanded || sheetDrag.expandedTall;
  const panelClass = [
    'transits-panel',
    isExpanded ? 'transits-panel--expanded' : '',
    sheetDrag.expandedTall ? 'sheet--tall' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <aside
      className={panelClass}
      style={
        sheetDrag.dragOffset !== 0
          ? { transform: `translateY(${String(sheetDrag.dragOffset)}px)` }
          : undefined
      }
      aria-label="En tránsito ahora"
    >
      <button
        type="button"
        className="transits-panel__toggle"
        aria-label="Lista de tránsitos"
        aria-expanded={isExpanded}
        aria-controls={bodyId}
        onPointerDown={(event) => {
          suppressClickRef.current = false;
          sheetDrag.handleProps.onPointerDown(event);
        }}
        onPointerMove={(event) => {
          if (Math.abs(sheetDrag.dragOffset) > 8) {
            suppressClickRef.current = true;
          }
          sheetDrag.handleProps.onPointerMove(event);
        }}
        onPointerUp={sheetDrag.handleProps.onPointerUp}
        onPointerCancel={sheetDrag.handleProps.onPointerCancel}
        onClick={() => {
          if (suppressClickRef.current) {
            suppressClickRef.current = false;
            return;
          }
          setExpanded((value) => {
            if (value || sheetDrag.expandedTall) {
              sheetDrag.resetTall();
              return false;
            }
            return true;
          });
        }}
      />
      <h2>
        En tránsito ahora
        {data !== undefined && (
          <>
            {' '}
            <span className="transits-panel__count">({data.total})</span>
          </>
        )}
      </h2>
      <div id={bodyId} className="transits-panel__body">
        {transits.isPending && <Skeleton lines={3} />}
        {transits.isError && (
          <div className="panel__error">
            <p className="transits-panel__error" role="alert">
              {friendlyError(transits.error, 'No se pudieron cargar los tránsitos activos.')}
            </p>
            <button
              type="button"
              className="panel__retry"
              onClick={() => {
                void transits.refetch();
              }}
            >
              Reintentar
            </button>
          </div>
        )}
        {data?.items.length === 0 && (
          <div className="transits-panel__empty-box">
            <p className="transits-panel__empty">Ningún buque en tránsito.</p>
            <p className="transits-panel__coverage">
              La cobertura AIS terrestre del Canal es parcial; algunos cruces pueden no quedar
              registrados.
            </p>
          </div>
        )}
        {data !== undefined && data.items.length > 0 && (
          <ul>
            {data.items.map((transit) => (
              <TransitRow
                key={transit.id}
                transit={transit}
                now={now}
                medianMinutes={medianMinutes}
                selected={transit.mmsi === selectedMmsi}
                onSelect={select}
              />
            ))}
          </ul>
        )}
        {data !== undefined && data.total > data.items.length && (
          <p className="transits-panel__note">
            Se muestran {data.items.length} de {data.total}.
          </p>
        )}
      </div>
    </aside>
  );
}

interface TransitRowProps {
  transit: CurrentTransit;
  now: number;
  medianMinutes?: number | null | undefined;
  selected: boolean;
  onSelect: (mmsi: number) => void;
}

function TransitRow({ transit, now, medianMinutes, selected, onSelect }: TransitRowProps) {
  const isSouth = transit.direction === 'southbound';
  const progress = transitProgress(transit.entered_at, now, medianMinutes);
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
          <span
            className={
              isSouth
                ? 'transits-panel__dir-badge transits-panel__dir-badge--south'
                : 'transits-panel__dir-badge transits-panel__dir-badge--north'
            }
            aria-hidden="true"
          >
            <svg viewBox="0 0 12 12" width="10" height="10" focusable="false">
              <path
                d={isSouth ? 'M6 1.5v9M2.5 7 6 10.5 9.5 7' : 'M6 10.5v-9M2.5 5 6 1.5 9.5 5'}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          {directionText(transit.direction)} · {elapsedText(transit.entered_at, now)}
        </span>
        {progress !== null && (
          <span className="transits-panel__progress">
            <span
              className="transits-panel__progress-track"
              role="progressbar"
              aria-label={`Avance estimado de ${transitName(transit.vessel_name, transit.mmsi)}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress.percent}
            >
              <span
                className="transits-panel__progress-fill"
                style={{ width: `${String(progress.percent)}%` }}
              />
            </span>
            <span className="transits-panel__progress-label">{progress.label}</span>
          </span>
        )}
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
