# ADR-0009: Segunda conexión a AISStream para buques con destino al Canal

- **Fecha**: 2026-10-22
- **Estado**: Aceptada
- **Modifica**: ADR-0002 y la regla 6 de `AGENTS.md` (una sola conexión por API key)

## Contexto
El dueño quiere ver los buques que, en cualquier parte del mundo, declaran como destino el Canal
de Panamá o uno de sus puertos (#59). El área del Canal no basta: esos buques están lejos.

- AISStream acepta **una combinación de cajas y tipos por suscripción**. La del worker es la bbox
  del Canal con `PositionReport` y `ShipStaticData`. Para ver destinos de todo el mundo hace falta
  otra suscripción, y por tanto otra conexión.
- Límites documentados: **3 conexiones suscritas por cuenta y 3 por IP** (ADR-0008). La regla
  "una conexión por key" del ADR-0002 era más estricta que el servicio.
- El destino solo viaja en `ShipStaticData` (cada ~6 min por buque). AISStream adjunta en
  `MetaData` la posición del buque (`latitude`/`longitude`).

Muestras reales con `ShipStaticData` de todo el mundo (solo recuentos, nada guardado):

| Fecha | Duración | Mensajes | Buques | Con posición | Con destino | Hacia el Canal |
|---|---|---|---|---|---|---|
| 2026-10-21 | 90 s | — | 1588 | — | — | 0 (2 falsos positivos con "CANAL") |
| 2026-10-22 | 90 s | 1457 | 1453 | 100 % | 86 % | 0 |
| 2026-10-22 | 7 min | 6170 | 5847 | 100 % | 86 % | 2 (`PA BLB`, `PANAMA`) |

En la de 7 min también aparecieron rutas que **salen** de Panamá (`PAMIT>ITVDL`,
`PACHG>COCOV`) y "canales" que no son el de Panamá (`HARVEY CANAL`, `DREDGING KIEL CANAL`).

## Decisión
1. El worker abre **como máximo dos conexiones**, cada una con su suscripción:
   - **área del Canal**: bbox del Canal, `PositionReport` + `ShipStaticData` (sin cambios);
   - **destinos**: bbox mundial `[[-90, -180], [90, 180]]`, solo `ShipStaticData`
     (~16 mensajes/s). Sin posiciones: serían cientos por segundo.

   Las dos viven en el mismo proceso `worker` (una réplica), con el mismo backoff y la key fuera
   de los logs. Se desactiva con `AIS_CANAL_BOUND_ENABLED=false`.
2. La segunda conexión tiene **su propia cola y su propio writer**
   (`app/workers/canal_bound_writer.py`). Si se atasca, la ingesta del área del Canal no lo nota.
3. La detección es una función pura (`app/services/canal_destination.py`) que reconoce:
   - códigos UN/LOCODE de puertos del Canal verificados en la lista de la UNECE (`PABLB`,
     `PACTB`, `PAONX`, `PAMIT`...), también con separador (`PA BLB`);
   - nombres propios de Panamá (`BALBOA`, `CRISTOBAL`, `COLON`, `RODMAN`) y `PANAMA`;
   - en una ruta, el destino final y los pasos intermedios, **no el origen** (primer tramo).

   Ante la duda, no cuenta: `MANZANILLO` solo (también es un puerto de México), `PANAMA CITY`
   (suele ser la de Florida) o un nombre junto a otro país (`COLON AR`, `BALBOA CA`).
4. Se guarda el último informe por buque en una tabla nueva, `canal_bound_vessels` (destino
   declarado, puerto detectado, ETA, última posición de `MetaData`, hora del informe). Va
   separada de `vessels`, que son los buques vistos en el área del Canal. Si un buque guardado
   declara otro destino, se borra.
5. `GET /api/v1/vessels/canal-bound`, con sesión (ADR-0008), paginado, filtro por puerto y por
   antigüedad del informe (30 días por defecto, máx. 90). Orden: ETA próximas primero, después
   las vencidas hace más de un día y al final las vacías.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Ampliar la bbox de la única conexión a todo el mundo | Llegarían también las posiciones de todo el mundo: cientos de mensajes por segundo para guardar casi nada |
| Una sola conexión mundial con solo `ShipStaticData` | Se pierden las posiciones del Canal, que son el núcleo del proyecto |
| Un segundo proceso `worker` para los destinos | Más despliegue y otra réplica que coordinar para lo mismo; una cola propia ya aísla el fallo |
| Columnas de destino en `vessels` | Mezcla "visto en el Canal" con "viene al Canal"; la API de buques y los tránsitos (Fase 5) esperan lo primero |
| Proveedor AIS de pago (satélite) | Coste; se decidirá en el ADR-0010 si la cobertura terrestre no basta |

## Consecuencias
- Se usan 2 de las 3 conexiones de la cuenta: queda una libre (por ejemplo para
  `scripts/ais_coverage.py`, que no debe correr a la vez que dos workers).
- **Qué NO se detecta**: los buques que cruzan el Canal sin declararlo (un Houston → Shanghái
  declara `CNSHA`); los que están en alta mar, fuera del alcance de los receptores terrestres
  (~40 NM); los que escriben el destino de forma no reconocible. Con la cobertura actual se
  esperan **pocos buques** (2 de 5847 en 7 minutos).
- **Destinos sin actualizar**: en la prueba real del 2026-10-22 (3 min con las dos conexiones),
  el único buque guardado estaba frente a Noruega, declaraba `PANAMA` y su ETA era de junio. La
  tripulación no siempre actualiza destino y ETA; por eso las ETA vencidas van al final y la
  lista se acota por antigüedad del informe.
- El destino es texto libre que escribe la tripulación: se valida en el parser (sin caracteres
  de control, máx. 64) y se devuelve como texto, nunca como HTML (AGENTS.md §8.6, §8.7).
- La lista de patrones se amplía con tests: cada falso positivo real que aparezca se añade a
  `tests/test_canal_destination.py` antes de cambiar la detección.
