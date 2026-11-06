# ADR-0013: Las estadísticas de tránsitos usan SQL; los agregados continuos, las posiciones

- **Fecha**: 2026-11-06
- **Estado**: Aceptada
- **Modifica**: la tarea 6.3 del roadmap y la lista de usos de agregados continuos de ADR-0005

## Contexto
ADR-0005 y la tarea 6.3 prevén "agregados continuos de TimescaleDB para estadísticas". Un
agregado continuo solo se puede crear sobre una **hypertable**, y la única que hay es
`positions`. Las estadísticas de la 6.4 (tránsitos por día y sentido, duraciones, esperas) salen de
`transits` y `anchorage_visits`, que son tablas normales: el Canal tiene del orden de 30 a 40
tránsitos al día, así que son decenas de filas por día, no millones.

## Decisión
- **Tránsitos y esperas (6.4)**: se calculan en SQL en cada consulta (`GROUP BY` sobre
  `entered_at`, `percentile_cont` para p50 y p90), con los índices que ya tienen. A este volumen
  no hace falta materializar nada, y un agregado continuo no sería posible sin convertir esas
  tablas en hypertables, que es complicación sin beneficio.
- **Posiciones (6.3)**: el agregado continuo `positions_hourly` (una fila por buque y hora, con
  el número de posiciones y la velocidad media y máxima) sirve para el tráfico (buques distintos
  por día) y para medir la cobertura de AISStream (mensajes por hora), que es el dato que más
  falta hace para la validación de la tarea 5.7. Con la misma técnica se hará el histórico
  reducido de la 6.5.
- `positions_hourly` es de **tiempo real** (`materialized_only = false`): una consulta suma a lo
  materializado las posiciones posteriores a la marca de agua. Una política lo refresca cada
  30 minutos y no materializa la última hora (`end_offset`). El primer refresco cubre todo el
  histórico (`start_offset = NULL`).

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Hypertables para `transits` y `anchorage_visits` | Decenas de filas al día; añade particionado sin ganar nada |
| Vistas materializadas de PostgreSQL con `REFRESH` manual | Hay que programar el refresco a mano; no hace falta a este volumen |
| Agregado continuo `positions_daily` con `count(DISTINCT vessel_mmsi)` | TimescaleDB 2.30 lo admite (se comprobó creándolo), pero pierde la cobertura por hora y por buque, y no se puede volver a agrupar por otra ventana; con una fila por buque y hora se cuentan al leer |

## Consecuencias
- Una posición que llega **tarde** a una hora ya materializada no aparece hasta el siguiente
  refresco (como mucho 30 minutos): el tiempo real solo suma lo posterior a la marca de agua. Las
  posiciones de AIS llegan casi al instante, así que afecta a pocas.
- Cada refresco recalcula solo las horas con datos nuevos (TimescaleDB lleva un registro de lo
  invalidado), así que el `start_offset = NULL` no repite trabajo.
- `canal_app` solo puede leer la vista (los permisos por defecto de `canal_owner` ya lo cubren);
  no puede borrarla ni modificarla.
- El roadmap sigue teniendo seis tareas en la Fase 6: la 6.3 queda como "agregados continuos
  sobre las posiciones" y la 6.4 lee de `transits`, `anchorage_visits` y `positions_hourly`.
