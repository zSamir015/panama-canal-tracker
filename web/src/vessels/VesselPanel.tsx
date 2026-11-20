import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { LiveVessel } from '../live/protocol';
import { CATEGORY_COLORS, CATEGORY_LABELS, shipCategory } from '../map/vesselGeoJson';
import type { CurrentTransit } from '../transits/api';
import { directionText, elapsedText } from '../transits/format';
import { friendlyError } from '../ui/errors';
import { Skeleton } from '../ui/Skeleton';
import { useSheetDrag } from '../ui/useSheetDrag';
import {
  agoText,
  aisTypeCodeText,
  courseText,
  dimensionsText,
  navStatusText,
  panamaDateTimeText,
  speedText,
} from './format';
import { useVesselDetail } from './queries';

interface VesselPanelProps {
  mmsi: number;
  token: string;
  /** Última posición recibida por `/ws/live`; manda sobre la de la ficha, que es más vieja. */
  live: LiveVessel | undefined;
  /** Tránsito activo si este buque está cruzando el Canal ahora mismo. */
  currentTransit?: CurrentTransit | undefined;
  onClose: () => void;
}

/**
 * Ficha del buque seleccionado. Todo lo que viene de AIS (nombre incluido) se pinta como texto con
 * React, nunca como HTML (AGENTS.md §8.7).
 */
export function VesselPanel({ mmsi, token, live, currentTransit, onClose }: VesselPanelProps) {
  const detail = useVesselDetail(mmsi, token);
  const now = useNow(5000);
  const [copied, setCopied] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const copyTimerRef = useRef<number | null>(null);

  const handleClose = useCallback(() => {
    const opener = openerRef.current;
    onClose();
    if (opener?.isConnected) {
      opener.focus();
    }
  }, [onClose]);

  const sheetDrag = useSheetDrag({ onDismiss: handleClose });

  useEffect(() => {
    openerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus({ preventScroll: true });
    return () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [handleClose]);

  const copyMmsi = useCallback(() => {
    const text = String(mmsi);
    try {
      void navigator.clipboard.writeText(text).catch(() => undefined);
    } catch {
      // Portapapeles no disponible en este entorno.
    }
    setCopied(true);
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = window.setTimeout(() => {
      setCopied(false);
    }, 1800);
  }, [mmsi]);

  const data = detail.data;
  const position = data?.last_position;
  const name = live?.name ?? data?.name ?? null;
  const shipType = live?.ship_type ?? data?.ship_type ?? null;
  const category = shipCategory(shipType);
  const signalIso = live?.ts ?? position?.received_at ?? null;
  const signalPanamaTitle = panamaDateTimeText(signalIso);
  const transitEnteredTitle =
    currentTransit === undefined ? undefined : panamaDateTimeText(currentTransit.entered_at);
  const transitId = useId();
  const movementId = useId();
  const vesselId = useId();

  return (
    <aside
      className={sheetDrag.expandedTall ? 'vessel-panel sheet--tall' : 'vessel-panel'}
      style={
        sheetDrag.dragOffset !== 0
          ? { transform: `translateY(${String(sheetDrag.dragOffset)}px)` }
          : undefined
      }
      aria-label="Ficha del buque"
    >
      <div
        className="vessel-panel__drag"
        aria-hidden="true"
        onPointerDown={sheetDrag.handleProps.onPointerDown}
        onPointerMove={sheetDrag.handleProps.onPointerMove}
        onPointerUp={sheetDrag.handleProps.onPointerUp}
        onPointerCancel={sheetDrag.handleProps.onPointerCancel}
      >
        <span className="sheet-handle__pill" />
      </div>
      <header
        className="vessel-panel__header"
        onPointerDown={(event) => {
          if (event.target instanceof Element && event.target.closest('button') !== null) {
            return;
          }
          sheetDrag.handleProps.onPointerDown(event);
        }}
        onPointerMove={sheetDrag.handleProps.onPointerMove}
        onPointerUp={sheetDrag.handleProps.onPointerUp}
        onPointerCancel={sheetDrag.handleProps.onPointerCancel}
      >
        <h2 ref={headingRef} tabIndex={-1}>
          {displayName(name)}
        </h2>
        <button
          type="button"
          className="vessel-panel__close"
          onClick={handleClose}
          aria-label="Cerrar la ficha"
        >
          ×
        </button>
      </header>
      <p className="vessel-panel__meta">
        {/* El color va en el punto; el texto queda oscuro para leerse siempre (WCAG AA). */}
        <span className="vessel-panel__type">
          <span
            className="vessel-panel__swatch"
            style={{ background: CATEGORY_COLORS[category] }}
          />
          {CATEGORY_LABELS[category]}
        </span>
        <span className="vessel-panel__mmsi-wrap">
          <span className="vessel-panel__mmsi">MMSI {mmsi}</span>
          <button
            type="button"
            className="vessel-panel__copy"
            aria-label={copied ? 'MMSI copiado' : 'Copiar MMSI'}
            onClick={copyMmsi}
          >
            {copied ? 'Copiado' : 'Copiar'}
          </button>
        </span>
      </p>
      {detail.isPending && <Skeleton lines={8} />}
      {detail.isError && (
        <div className="panel__error">
          <p className="vessel-panel__error" role="alert">
            {friendlyError(detail.error, 'No se pudo cargar la ficha del buque.')}
          </p>
          <button
            type="button"
            className="panel__retry"
            onClick={() => {
              void detail.refetch();
            }}
          >
            Reintentar
          </button>
        </div>
      )}
      {!detail.isPending && (
        <>
          {currentTransit !== undefined && (
            <div
              className="vessel-panel__group vessel-panel__group--transit"
              role="group"
              aria-labelledby={transitId}
            >
              <h3 id={transitId}>Tránsito en curso</h3>
              <dl>
                <dt>Sentido</dt>
                <dd>{directionText(currentTransit.direction)}</dd>
                <dt>Entrada</dt>
                <dd>
                  <time dateTime={currentTransit.entered_at} title={transitEnteredTitle}>
                    {transitEnteredTitle ?? '—'}
                  </time>
                  {' · '}
                  {elapsedText(currentTransit.entered_at, now)}
                </dd>
              </dl>
            </div>
          )}
          <div className="vessel-panel__group" role="group" aria-labelledby={movementId}>
            <h3 id={movementId}>Movimiento</h3>
            <dl>
              <dt>Velocidad</dt>
              <dd>{speedText(live?.sog ?? position?.sog ?? null)}</dd>
              <dt>Rumbo</dt>
              <dd>{courseText(live?.cog ?? position?.cog ?? null)}</dd>
              <dt>Estado</dt>
              <dd>{navStatusText(position?.nav_status ?? null)}</dd>
              <dt>Última señal</dt>
              <dd>
                {signalIso !== null ? (
                  <time dateTime={signalIso} title={signalPanamaTitle}>
                    {agoText(signalIso, now)}
                  </time>
                ) : (
                  '—'
                )}
              </dd>
            </dl>
          </div>
          <div className="vessel-panel__group" role="group" aria-labelledby={vesselId}>
            <h3 id={vesselId}>Buque</h3>
            <dl>
              <dt>IMO</dt>
              <dd>{data?.imo ?? '—'}</dd>
              <dt>Eslora × manga</dt>
              <dd>{dimensionsText(data?.length_m ?? null, data?.beam_m ?? null)}</dd>
              <dt>Código AIS</dt>
              <dd>{aisTypeCodeText(shipType)}</dd>
            </dl>
          </div>
        </>
      )}
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
