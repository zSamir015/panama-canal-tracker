import type { DailyItem } from './api';

export interface DayBar {
  /** Día UTC, `AAAA-MM-DD`. */
  date: string;
  southbound: number;
  northbound: number;
}

const DAY_MS = 86_400_000;

/**
 * Una barra por día, de `days` días hasta el día UTC de `now` (incluido). La API solo devuelve los
 * días con tránsitos; aquí se rellenan los vacíos con 0 para que el eje del tiempo no tenga
 * saltos. Los tránsitos de fuera del rango no se cuentan.
 */
export function dailySeries(items: readonly DailyItem[], days: number, now: number): DayBar[] {
  const lastDay = Math.floor(now / DAY_MS);
  const bars = new Map<string, DayBar>();
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = new Date((lastDay - offset) * DAY_MS).toISOString().slice(0, 10);
    bars.set(date, { date, southbound: 0, northbound: 0 });
  }
  for (const item of items) {
    const bar = bars.get(item.date);
    if (bar !== undefined) {
      bar[item.direction] += item.transits;
    }
  }
  return [...bars.values()];
}

/** Total por categoría de buque, de mayor a menor (a igualdad, por nombre). */
export function categoryTotals(items: readonly DailyItem[]): [string, number][] {
  const totals = new Map<string, number>();
  for (const item of items) {
    totals.set(item.ship_category, (totals.get(item.ship_category) ?? 0) + item.transits);
  }
  return [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** El máximo del eje vertical: el mayor total diario, redondeado a un número "bonito". */
export function axisMax(bars: readonly DayBar[]): number {
  const peak = Math.max(0, ...bars.map((bar) => bar.southbound + bar.northbound));
  if (peak <= 4) {
    return 4;
  }
  const step = peak <= 10 ? 2 : peak <= 20 ? 5 : 10;
  return Math.ceil(peak / step) * step;
}

/**
 * Los datos de un tipo de buque, o todos con `null` (issue #129). La gráfica filtrada se dibuja
 * con estos datos; la escala se calcula siempre con todos (`axisMax` de la serie completa).
 */
export function itemsOfCategory(
  items: readonly DailyItem[],
  category: string | null,
): readonly DailyItem[] {
  return category === null ? items : items.filter((item) => item.ship_category === category);
}
