import { DIRECTION_COLORS } from './colors';
import { axisMax, type DayBar } from './series';
import { shortDateText } from './format';

const WIDTH = 640;
const HEIGHT = 240;
const MARGIN = { top: 12, right: 12, bottom: 28, left: 32 };
const GRID_LINES = 4;

interface BarChartProps {
  bars: readonly DayBar[];
}

/**
 * Barras apiladas por día (sentido sur y norte), dibujadas a mano en SVG: sin librería de
 * gráficas (menos dependencias que auditar). Cada barra lleva su `<title>`, que el navegador
 * enseña al pasar el ratón y los lectores de pantalla leen. Todo son números y fechas que
 * generamos nosotros: no hay texto de AIS aquí.
 */
export function BarChart({ bars }: BarChartProps) {
  const max = axisMax(bars);
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const slot = plotWidth / Math.max(1, bars.length);
  const barWidth = Math.max(1, slot * 0.7);
  const y = (value: number) => MARGIN.top + plotHeight - (value / max) * plotHeight;
  // Con 90 días no caben todas las fechas: una cada `labelEvery` barras.
  const labelEvery = Math.max(1, Math.ceil(bars.length / 8));
  const total = bars.reduce((sum, bar) => sum + bar.southbound + bar.northbound, 0);

  return (
    <svg
      className="bar-chart"
      viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
      role="img"
      aria-label={`Tránsitos completados por día: ${String(total)} en ${String(bars.length)} días`}
    >
      {Array.from({ length: GRID_LINES + 1 }, (_, line) => {
        const value = (max / GRID_LINES) * line;
        return (
          <g key={line}>
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={y(value)}
              y2={y(value)}
              className="bar-chart__grid"
            />
            <text x={MARGIN.left - 6} y={y(value) + 4} className="bar-chart__tick" textAnchor="end">
              {Number.isInteger(value) ? value : value.toFixed(1)}
            </text>
          </g>
        );
      })}
      {bars.map((bar, index) => {
        const x = MARGIN.left + slot * index + (slot - barWidth) / 2;
        const south = (bar.southbound / max) * plotHeight;
        const north = (bar.northbound / max) * plotHeight;
        return (
          <g key={bar.date}>
            <title>
              {`${shortDateText(bar.date)}: ${String(bar.southbound + bar.northbound)} tránsitos ` +
                `(Atlántico → Pacífico ${String(bar.southbound)}, ` +
                `Pacífico → Atlántico ${String(bar.northbound)})`}
            </title>
            <rect
              x={x}
              y={y(0) - south}
              width={barWidth}
              height={south}
              fill={DIRECTION_COLORS.southbound}
            />
            <rect
              x={x}
              y={y(0) - south - north}
              width={barWidth}
              height={north}
              fill={DIRECTION_COLORS.northbound}
            />
            {index % labelEvery === 0 && (
              <text
                x={x + barWidth / 2}
                y={HEIGHT - MARGIN.bottom + 16}
                className="bar-chart__tick"
                textAnchor="middle"
              >
                {shortDateText(bar.date)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
