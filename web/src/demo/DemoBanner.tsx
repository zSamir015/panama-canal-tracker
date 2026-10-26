/** Banner visible en modo demo para evitar confusión con datos reales (ADR-0011). */
export function DemoBanner() {
  return (
    <div className="demo-banner" role="status" aria-label="Datos simulados">
      ⚠ Datos simulados — esta demo no usa datos AIS reales
    </div>
  );
}
