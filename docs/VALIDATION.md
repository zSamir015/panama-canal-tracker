# Validación con datos reales (tarea 5.7)

Primera validación del detector de tránsitos contra posiciones AIS reales. **Resultado corto: con
la cobertura actual de AISStream no se puede validar la precisión del detector, y la cobertura
es el problema, no los umbrales.** Este documento dice qué se midió, qué no, y qué hacer.

## Datos

- Recolector `Collect AIS` (ADR-0012), 14 ejecuciones legibles, del 2026-11-07 01:39Z al
  2026-11-12 13:00Z (5,5 días). La ejecución 42323599406 es ilegible (passphrase perdida) y no
  cuenta.
- **73,4 h de escucha de ~131 h transcurridas (56 %)**: GitHub retrasa u omite ejecuciones
  programadas (ventanas de ~5,6 h cada ~8-12 h).
- 4 984 posiciones de 310 buques en la caja del Canal. Solo **72 posiciones (1,4 %) caen dentro de
  alguna zona de entrada** (57 Atlántico, 15 Pacífico) y 45 buques pisan una zona.
- Procedimiento: descargar artefactos, descifrar, `python scripts/transit_replay.py
  data/collected/ais-*.jsonl --timeout-minutes N`. Los datos no se versionan.

## Resultados del replay

| timeout | completados | abortados | en curso |
|---|---|---|---|
| 30 min (actual) | 0 | 46 (todos timeout) | 0 |
| 60 a 240 min | 0 | 46 | 0 |
| 600 min | 1 | 42 | 3 |
| 1 440 min | 2 | 38 (37 timeout, 1 reversal) | 5 |

Los dos tránsitos completos, únicos con AIS en ambos extremos:

| MMSI | sentido | entrada | salida | duración |
|---|---|---|---|---|
| 259001000 | sur | 11-10 12:27Z | 11-10 22:34Z | 10 h 08 min |
| 636022111 | sur | 11-08 07:16Z | 11-09 02:04Z | 18 h 48 min (incluye una parada larga en el Atlántico y otra en el Pacífico) |

Entre una zona y otra **no llega ninguna posición**: AISStream no cubre el Gatún ni el Corte
Culebra. Un tránsito real dura ~10 h, así que con timeout de 30 min es imposible completar
ninguno, y subirlo hasta 240 min tampoco cambia nada.

## Comparación con la ACP

La ACP informa ~35 tránsitos/día de media en el año fiscal 2026 (10 726 de octubre a junio,
[resumen citado por FreshPlaza](https://www.freshplaza.com/asia/article/9832315/panama-canal-transits-rise-to-6-288-in-first-half-of-fy2026/);
ficha mensual en [pancanal.com](https://pancanal.com/wp-content/uploads/2026/07/ADV-23-2026-Monthly-Canal-Operations-Summary-June-2026.pdf),
no abierta por mí). Esperados en 5,5 días: ~190; ajustando por el 56 % de tiempo escuchado:
~107. Detectados: 2 (1-2 %). **No es una medida de precisión del detector**: mide la cobertura.
No hay estadísticas diarias públicas de la ACP por buque, así que no se pudo cruzar tránsito a
tránsito.

## Hallazgos

1. **Cobertura**: sin posiciones dentro del Canal, el detector solo puede ver extremo a extremo
   en los pocos casos en que el buque emite en ambas entradas. Sin otra fuente (receptor
   propio, proveedor de pago) la tabla `transits` seguirá casi vacía con datos reales.
2. **Sentido ambiguo en la entrada**: el sentido se deduce de la primera zona pisada. Usando el
   rumbo (COG) de la primera posición en movimiento dentro de la zona, aproximadamente **la
   mitad de los buques entra y la otra mitad sale** (Atlántico: 12 entran, 15 salen; Pacífico: 6 y
   6). Un buque que sale del Canal y cruza la zona se registra como tránsito iniciado en sentido
   contrario y acaba abortado. Probablemente explica buena parte de los 46 abortos (no lo he
   contado tránsito a tránsito) y sería un fallo del diseño que los tests sintéticos no podían
   ver. *Es una estimación con un umbral de
   rumbo tosco y polígonos aproximados, no un recuento verificado.*
3. **Polígonos y zonas**: no hay evidencia contra ellos, pero tampoco a favor: 72 posiciones es
   poco para juzgarlos. 6 buques tienen su última posición dentro de la zona del Atlántico con
   sog < 1 kn, es decir, parados dentro del polígono de entrada; puede indicar que el polígono
   invade una zona de espera, pero 6 casos no bastan para redibujarlo.
4. **Fondeaderos y enlace de espera (15 min/1 kn, 24 h)**: sin datos suficientes. 636022111
   estuvo parado (0,0-0,4 kn) unas 19 h al sur de la zona del Pacífico (del 11-09 03:51Z al
   23:03Z, con huecos sin señal) y luego siguió hacia el sur, un caso consistente con una
   espera tras salir del Canal, pero uno solo. Este informe no pasa los datos por
   `app/services/anchorage_detector.py`.

## Umbrales: qué se cambia y qué no

- **No se cambia ningún umbral por esto.** Con 2 tránsitos reales no hay base para ajustar nada.
  Subir el timeout a 24 h haría completar esos 2, pero también mantendría abiertos 5 abortos
  hoy cerrados y no mejora la precisión, solo la sensibilidad.
- Si se elige timeout largo, debe ir con la solución del punto 2 (decidir entrada o salida por
  el rumbo o por la secuencia), porque si no los buques que salen quedan abiertos un día entero.

## Después del issue #121: el rumbo decide si entra o sale

El hallazgo 2 se corrigió (ADR-0016): un buque que pisa una zona de entrada con rumbo hacia el
mar ya no abre un tránsito. Mismos datos y mismo procedimiento:

| timeout | antes | después |
|---|---|---|
| 30 min (actual) | 0 completados, 46 abortados | 0 completados, 24 abortados (timeout) |
| 1 440 min | 2 completados, 38 abortados, 5 en curso | 2 completados, 19 abortados (18 timeout, 1 reversal), 3 en curso |

Desaparecen 22 tránsitos falsos y se mantienen los dos reales. Los 24 que quedan son buques que
se vieron entrar y nunca llegaron a la otra zona dentro del timeout: la falta de cobertura del
interior, que este cambio no puede arreglar.

## Siguiente

1. ~~Decidir si el sentido se infiere del rumbo~~: hecho en el issue #121 (ADR-0016).
2. Seguir recolectando; repetir con ≥ 14 días. Solo tiene sentido si cambia la cobertura.
3. Evaluar una fuente con cobertura dentro del Canal (ver `docs/DATA_SOURCES.md`); el dueño
   descartó gasto, así que la alternativa es aceptar el límite y documentarlo en el README (7.4).
4. La tarea 5.7 queda **abierta**: el informe está, la validación de precisión no es posible aún.
