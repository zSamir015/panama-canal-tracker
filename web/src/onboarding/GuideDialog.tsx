import { useEffect, useId, useRef } from 'react';

interface GuideDialogProps {
  open: boolean;
  /** En la demo no hay ficha, panel de tránsitos ni estadísticas (ADR-0011). */
  demo: boolean;
  /** Se llama al cerrarse por cualquier vía: "Entendido", la ✕ o Escape. */
  onClose: () => void;
}

const LIVE_STEPS = [
  'Pulsa un buque en el mapa para ver su ficha y la estela de su recorrido reciente.',
  'El color indica el tipo de buque. La Leyenda dice cuál es cuál.',
  '«En tránsito ahora» lista los buques que están cruzando el Canal. Pulsa uno para abrir su ficha.',
  'En Estadísticas tienes los tránsitos por día, cuánto duran y las esperas en los fondeaderos.',
];

const DEMO_STEPS = [
  'Arrastra y haz zoom para moverte por el Canal. Los buques avanzan solos.',
  'El color indica el tipo de buque. La Leyenda dice cuál es cuál.',
  'Los datos son simulados. La versión con datos AIS reales añade la ficha de cada buque, los tránsitos en curso y estadísticas.',
];

/**
 * Guía al primer uso (issue #137). Es un `<dialog>` nativo abierto con `showModal()`: el
 * navegador atrapa el foco, deja el fondo inerte, cierra con Escape y devuelve el foco al cerrar.
 */
export function GuideDialog({ open, demo, onClose }: GuideDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) {
      return;
    }
    if (open && !dialog.open) {
      dialog.showModal();
      // El navegador enfocaría la ✕ (lo primero enfocable); la acción principal es "Entendido".
      okRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const close = () => {
    ref.current?.close();
  };

  return (
    <dialog
      ref={ref}
      className="guide"
      aria-labelledby={titleId}
      onClose={onClose}
      onKeyDown={(event) => {
        // La ficha del buque se cierra con Escape escuchando en `window`: que no se cierre también.
        if (event.key === 'Escape') {
          event.stopPropagation();
        }
      }}
    >
      <div className="guide__header">
        <h2 id={titleId}>Cómo usar el tracker</h2>
        <button type="button" className="guide__close" aria-label="Cerrar la guía" onClick={close}>
          ✕
        </button>
      </div>
      <ol className="guide__steps">
        {(demo ? DEMO_STEPS : LIVE_STEPS).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <button ref={okRef} type="button" className="guide__ok" onClick={close}>
        Entendido
      </button>
    </dialog>
  );
}
