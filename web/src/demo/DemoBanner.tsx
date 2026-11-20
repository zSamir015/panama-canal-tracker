interface DemoBannerProps {
  onExit?: (() => void) | undefined;
}

/** Banner visible en modo demo para evitar confusión con datos reales (ADR-0011). */
export function DemoBanner({ onExit }: DemoBannerProps) {
  return (
    <div className="demo-banner" role="status" aria-label="Datos simulados">
      <span>⚠ Datos simulados — esta demo no usa datos AIS reales</span>
      {onExit !== undefined && (
        <button type="button" className="demo-banner__exit" onClick={onExit}>
          Volver al inicio de sesión
        </button>
      )}
    </div>
  );
}
