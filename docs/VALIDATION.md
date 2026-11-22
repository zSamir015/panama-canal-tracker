# Validación con datos reales (tarea 5.7)

Validación del detector de tránsitos contra posiciones AIS reales recogidas durante **14,9 días**
(repetida el `2026-11-21` con el mínimo de 14 días que fijó el dueño; la primera pasada, con 12,5
días, daba la misma conclusión).
**Conclusión**: con la cobertura gratuita actual de AISStream no es posible validar la precisión
del detector frente a la ACP ni recalibrar umbrales y polígonos con rigor; la cobertura dentro del
Canal es el factor limitante, no los umbrales del algoritmo. Con los 14,9 días documentados y sin
presupuesto para una fuente comercial, se acepta esta limitación y queda cerrada la tarea 5.7.

## Datos

- Recolector `Collect AIS` (ADR-0012), **37 ejecuciones legibles** (36 ventanas de ~5,6 h y la
  prueba inicial `42325039999` de 4 min), del `2026-11-07 01:39Z` al `2026-11-21 22:03Z`
  (**14,85 días**, `356,4 h`). La ejecución `42323599406` es ilegible (passphrase perdida) y no
  cuenta.
- **201,4 h de escucha de 356,4 h transcurridas (56,5 %)**: GitHub retrasa u omite ejecuciones
  programadas (ventanas de ~5,0–5,7 h cada ~8–12 h). Desde la ventana del `2026-11-20 06:23Z`, con
  el encadenado de ADR-0019, las ventanas son consecutivas (7 seguidas, 99,4 % de escucha en esas
  ~40 h); el 56,5 % es el promedio de todo el periodo.
- **10 040 posiciones** de **595 buques** en la caja del Canal (más 5 499 líneas estáticas).
  Solo **86 posiciones (0,9 %)** caen dentro de alguna zona de entrada (57 Atlántico, 29 Pacífico),
  de **58 buques únicos** (33 en Atlántico, 27 en Pacífico, 2 en ambas).
- Procedimiento: descargar artefactos, descifrar, `PYTHONPATH=. python scripts/transit_replay.py
  data/collected/ais-*.jsonl --timeout-minutes N`. Los datos no se versionan.

### Caída de la cobertura entre semanas

La cobertura voluntaria se degradó notablemente durante la segunda mitad del periodo:

| Tramo | Posiciones | Buques | Entrada Atl. | Entrada Pac. | Fondeadero Atl. | Fondeadero Pac. |
|---|---|---|---|---|---|---|
| 7–12 nov (`14` runs, 5,5 d) | 4 984 | 310 | 57 | 15 | 406 | 1 343 |
| 12–19 nov (`15` runs, 7,0 d) | 3 302 | 255 | **0** | 12 | **1** | 1 506 |
| 19–21 nov (`8` runs, 2,0 d) | 1 754 | 119 | **0** | 2 | **0** | 134 |
| **Total (`37` runs, 14,9 d)** | **10 040** | **595** | **57** | **29** | **407** | **2 983** |

A partir del `2026-11-12` dejó de recibirse cobertura en el lado Atlántico (`0` posiciones en la
entrada y `1` en el fondeadero en 7 días), y desde la noche del `2026-11-16` el volumen total
cayó de ~280–630 posiciones por ventana a **44–95 posiciones** por ventana. Desde el `2026-11-20`
el volumen por ventana volvió a **180–420 posiciones**, pero **el lado Atlántico sigue sin
señal** (`0` posiciones en su entrada y `1` en su fondeadero desde el `2026-11-12`) y el interior
del Canal sigue vacío: la recuperación es de volumen, no de cobertura donde hace falta. No se sabe
si es un cambio en la red de receptores o una variación pasajera.

## Resultados del replay

### Primera pasada (7–12 nov, 5,5 días, antes y después de ADR-0016)

En los primeros 5,5 días (`4 984` posiciones de `310` buques; `73,4 h` de escucha = `56 %`), la
primera versión del detector producía **46 abortados** y **0 completados** con el timeout de
30 min. El issue #121 (`ADR-0016`) corrigió el hallazgo principal —un buque que sale del Canal por
una zona de entrada con rumbo hacia el mar ya no abre tránsito— y eliminó casi la mitad de los
abortos falsos sobre esos mismos datos:

| timeout | antes de ADR-0016 | después de ADR-0016 |
|---|---|---|
| 30 min (actual) | 0 completados, 46 abortados | 0 completados, 24 abortados (timeout) |
| 1 440 min | 2 completados, 38 abortados, 5 en curso | 2 completados, 19 abortados (18 timeout, 1 reversal), 3 en curso |

### Periodo completo (7–21 nov, 14,9 días, con ADR-0016)

| timeout | completados | abortados | en curso |
|---|---|---|---|
| 30 min (actual) | 0 | 31 (todos `timeout`) | 0 |
| 60 a 240 min | 0 | 31 (todos `timeout`) | 0 |
| 600 min | 1 | 30 (todos `timeout`) | 0 |
| 1 440 min | 2 | 28 (27 `timeout`, 1 `reversal`) | 1 |

El tránsito en curso con 1 440 min es el del MMSI `636023849` (sentido norte, entró por el
Pacífico el `2026-11-21 08:53Z`): lleva menos de 24 h abierto cuando se corta el periodo, así que
no es un fallo. Los completados son los mismos dos que en la pasada de 12,5 días.

Los dos únicos tránsitos completos (con AIS en ambas entradas, ambos del 8–10 nov antes de caer la
cobertura atlántica; no ha aparecido ninguno nuevo en los 4 días añadidos al periodo):

| MMSI | sentido | entrada | salida | duración |
|---|---|---|---|---|
| 636022111 | `southbound` | 11-08 07:16Z | 11-09 02:04Z | 18 h 48 min (incluye paradas en ambos extremos) |
| 259001000 | `southbound` | 11-10 12:27Z | 11-10 22:34Z | 10 h 08 min |

En el corredor interior del Canal (`lat 8.98..9.30`, `lon -79.96..-79.58`) solo aparecieron **26
posiciones de 16 buques** en 14,9 días (concentradas cerca de Gatún; prácticamente nada en el
Corte Culebra ni en Miraflores). Un tránsito real dura ~10 h; sin señal intermedia, ningún
timeout entre 30 min y 240 min puede completar tránsitos de extremo a extremo.

## Comparación con la ACP

La ACP informa ~35 tránsitos/día de media en el año fiscal 2026 (10 726 de octubre a junio,
[resumen citado por FreshPlaza](https://www.freshplaza.com/asia/article/9832315/panama-canal-transits-rise-to-6-288-in-first-half-of-fy2026/);
ficha mensual en [pancanal.com](https://pancanal.com/wp-content/uploads/2026/07/ADV-23-2026-Monthly-Canal-Operations-Summary-June-2026.pdf),
no abierta directamente). En 14,9 días se esperarían ~520 tránsitos (~294 ajustando al 56,5 % de
tiempo escuchado). Detectados incluso con timeout de 24 h: **2 (< 1 %)**. **Esto mide la
cobertura de AISStream en Panamá, no la precisión del detector.** Tampoco existen estadísticas
diarias públicas por buque para cruzar tránsito a tránsito.

## Hallazgos

1. **Cobertura**: sin receptores que cubran el interior del Canal (y desde el 12 de noviembre ni
   siquiera el lado Atlántico, que a 21 de noviembre sigue sin señal), el detector solo puede enlazar extremo a extremo cuando un buque
   emite en ambas entradas durante ventanas activas. Sin receptor propio ni proveedor comercial, la
   tabla `transits` con AISStream gratuito contendrá pocos tránsitos reales.
2. **Sentido en la entrada (`ADR-0016`)**: resuelto en #121. Evita abrir falsos tránsitos con los
   buques que salen del Canal; en los 14,9 días completos solo quedan 31 abortos por timeout frente
   a los 46 iniciales de apenas 5,5 días. Los rumbos de referencia se basaron en 39 buques en
   movimiento de la primera semana (en la segunda semana ya no hubo entradas atlánticas para
   contrastar más).
3. **Polígonos de entrada (`app/services/zones.py`)**: 86 posiciones en 14,9 días siguen siendo
   insuficientes para redibujar las entradas. En la primera semana, 6 buques tuvieron su última
   posición en la entrada del Atlántico con `sog < 1 kn`; el dato no aumentó después al caer el
   receptor atlántico.
4. **Fondeaderos (`app/services/anchorages.py` y `anchorage_detector.py`)**: al pasar los
   10 040 registros por `anchorage_detector.on_position` con el timeout actual de `30 min` se
   cierran **307 visitas** (270 en el Pacífico, 37 en el Atlántico, contando las que siguen
   abiertas al terminar los datos; con `240 min` son 206 visitas, 181 y 25, sin contar esas). Al
   mismo tiempo, **3 875 posiciones paradas (`sog < 0,5 kn`) de 194 buques** caen fuera de los
   rectángulos aproximados (3 166 de 132 buques en el lado Pacífico y 709 de 70 en el
   Atlántico), mezcla de buques atracados en terminales y buques fondeados fuera de la caja actual.

## Umbrales: qué se cambia y qué no

- **No se cambian umbrales ni polígonos sin datos de cobertura completa.** Subir el timeout de
  30 min a 24 h sobre datos sin cobertura interior solo mantendría abiertos durante un día entero
  los tránsitos perdidos por falta de señal (pasando de 30 a 28 abortos sin mejorar la tasa real).
- Las estadísticas calculadas sobre datos reales de AISStream deben interpretarse con esta
  limitación; el funcionamiento completo del detector y de los agregados queda verificado con el
  simulador y trayectorias sintéticas (`tests/test_transit_replay.py`, `tests/test_transit_detector.py`).

## Cierre de la tarea 5.7

1. ~~Decidir si el sentido se infiere del rumbo~~: hecho en el issue #121 (`ADR-0016`).
2. ~~Repetir el replay con más días recolectados~~: hecho hasta 14,9 días (`2026-11-07` a `2026-11-21`,
   el mínimo de 14 días fijado por el dueño); la cobertura no mejora donde hace falta: la entrada
   atlántica sigue sin señal desde el 12 nov y el interior del Canal sigue vacío, aunque el volumen
   por ventana se recuperó desde el 20 nov.
3. Se descarta contratar un proveedor comercial de AIS (`docs/DATA_SOURCES.md`), por lo que se
   acepta oficialmente el límite de cobertura de AISStream y **se cierra la tarea 5.7** (`v0.5.0`).
   Este límite quedará documentado explícitamente en el README final (tarea 7.4).
