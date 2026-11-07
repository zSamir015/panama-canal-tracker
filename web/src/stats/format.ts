const NO_DATA = '—';

/** "6 h 45 min" a partir de minutos; sin dato, un guion. */
export function minutesText(minutes: number | null): string {
  if (minutes === null) {
    return NO_DATA;
  }
  const total = Math.round(minutes);
  if (total < 60) {
    return `${String(total)} min`;
  }
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${String(hours)} h` : `${String(hours)} h ${String(rest)} min`;
}

/** "12 de nov" para una fecha `AAAA-MM-DD` (día UTC, sin pasar por la zona horaria). */
export function shortDateText(date: string): string {
  const [, month, day] = date.split('-');
  const names = [
    'ene',
    'feb',
    'mar',
    'abr',
    'may',
    'jun',
    'jul',
    'ago',
    'sep',
    'oct',
    'nov',
    'dic',
  ];
  const name = names[Number(month) - 1];
  return name === undefined ? date : `${String(Number(day))} ${name}`;
}

const CATEGORY_LABELS: Readonly<Record<string, string>> = {
  cargo: 'Carga',
  tanker: 'Tanquero',
  passenger: 'Pasajeros',
  tug: 'Remolcador / práctico',
  fishing: 'Pesca',
  pleasure: 'Recreo',
  other: 'Otro',
  unknown: 'Sin tipo',
};

/** Las mismas etiquetas que la leyenda del mapa; una categoría desconocida se muestra tal cual. */
export function categoryText(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}
