import type { LiveStatus } from '../live/useLiveVessels';
import { connectionTone } from './connection';

/**
 * Punto de color junto al texto del estado de la conexión (issue #127). Es decorativo
 * (`aria-hidden`): el estado lo dice el texto de al lado, que es lo que anuncia el lector de
 * pantalla y lo que se lee sin distinguir colores.
 */
export function ConnectionDot({ status }: { status: LiveStatus }) {
  return (
    <span
      className={`connection-dot connection-dot--${connectionTone(status)}`}
      aria-hidden="true"
    />
  );
}
