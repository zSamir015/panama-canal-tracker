interface SkeletonProps {
  /** `lines`: líneas de texto (fichas, listas, tablas). `chart`: un bloque del alto de una gráfica. */
  variant?: 'lines' | 'chart';
  lines?: number;
}

/**
 * Hueco gris con la forma de lo que va a llegar, en lugar de "Cargando…" (issue #127). Evita que la
 * interfaz salte cuando llegan los datos. Las formas son decorativas (`aria-hidden`); el lector de
 * pantalla oye "Cargando…" y `aria-busy`. No es `role="status"`: el estado de la conexión ya lo usa
 * y un segundo anuncio en cada carga sería ruido.
 */
export function Skeleton({ variant = 'lines', lines = 3 }: SkeletonProps) {
  return (
    <div className={`skeleton skeleton--${variant}`} aria-busy="true">
      <span className="visually-hidden">Cargando…</span>
      {variant === 'chart' ? (
        <span className="skeleton__block" aria-hidden="true" />
      ) : (
        Array.from({ length: lines }, (_, index) => (
          <span key={index} className="skeleton__line" aria-hidden="true" />
        ))
      )}
    </div>
  );
}
