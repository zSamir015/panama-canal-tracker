# ADR-0016: El rumbo (COG) decide si un buque entra o sale por una zona de entrada

- **Fecha**: 2026-11-12
- **Estado**: Aceptada
- **Issue**: #121

## Contexto
El detector de tránsitos (`app/services/transit_detector.py`, tarea 5.2) abría un tránsito con la
primera posición de un buque en una zona de entrada y deducía el sentido de esa zona: Atlántico,
`southbound`; Pacífico, `northbound`. Con datos sintéticos bastaba, porque todos los buques
simulados entraban.

La primera validación con datos reales (`docs/VALIDATION.md`, 5,5 días) dio 0 tránsitos completos
y 46 abortados con el timeout de 30 min. En la primera posición en movimiento dentro de cada zona,
el rumbo sobre el fondo (COG) formaba dos grupos muy separados:

| Zona | Entrando | Saliendo |
|---|---|---|
| Atlántico | ~180° (12 buques) | ~0° (15 buques) |
| Pacífico | ~321° (6 buques) | ~141° (6 buques) |

Aproximadamente la mitad de los buques **salía** del Canal. Como AISStream casi no cubre el
interior, a esos buques no se les ve entrar, solo salir. El detector abría con ellos un tránsito
en sentido contrario que nunca se completaba.

## Decisión
- Cada zona tiene un **rumbo de entrada** (`INBOUND_COG`: Atlántico 180°, Pacífico 321°), medido
  en esos datos. Un buque va **hacia dentro** si su COG está a menos de 90° de ese rumbo y **hacia
  fuera** si está a más. La diferencia se calcula con vuelta (entre 359° y 1° hay 2°).
- El rumbo es **desconocido** sin COG, sin SOG, con el buque parado (SOG < 1 nudo, `MOVING_SOG`;
  parado, el COG es ruido del GPS) o justo de través (90°).
- **Solo decide la apertura**. Sin tránsito abierto, si el buque sale, no se abre nada y debe
  dejar la zona antes de abrir otro (`must_leave`), para que sus posiciones paradas dentro del
  polígono no abran uno después. Si entra o no se sabe, se abre como antes. Un tránsito abierto se
  completa al llegar a la zona opuesta sin mirar el rumbo, porque ahí el buque ya navega hacia el
  mar.
- El replay (`scripts/transit_replay.py`) lee `sog` y `cog`; un valor inválido se descarta y la
  posición se conserva.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Descartar la posición cuando el rumbo es desconocido | Con la cobertura actual muchos buques dejan una sola posición en la zona; se perderían tránsitos reales |
| Deducir el sentido de la secuencia (zona después de la posición fuera) | Necesita posiciones a los dos lados del borde, justo lo que falta con AISStream |
| Cerrar un tránsito abierto cuando el buque apunta al mar | Pide un motivo de aborto nuevo, con cambios en la API, el esquema y los clientes; queda fuera de #121 |
| Usar `heading` (proa) en lugar del COG | El COG es el movimiento real; la proa no lo es con corriente o viento, y muchos buques no la emiten |
| Rumbos de entrada sacados de la geometría de los polígonos | Los polígonos son aproximados (tarea 5.1); los datos dan los rumbos directamente |

## Consecuencias
- Replay real (los mismos 5,5 días): con timeout de 30 min, 24 abortados en lugar de 46. Con 24 h,
  19 en lugar de 38, y los 2 tránsitos completos se mantienen. No cambia ningún umbral.
- Los rumbos de entrada salen de pocos buques (39 en movimiento dentro de una zona). Si cambian
  las rutas o los polígonos, hay que volver a medirlos.
- Un tránsito abierto sin rumbo fiable (buque parado en la zona) que después sale hacia el mar
  sigue abierto hasta el timeout o la reversa.
- Los tests que no tratan del rumbo usan COG desconocido; los del rumbo están en
  `tests/test_transit_direction.py`.
