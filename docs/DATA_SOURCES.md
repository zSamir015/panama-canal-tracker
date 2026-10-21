# Fuentes de datos — Panama Canal Tracker

## 1. AISStream.io (fuente principal)

WebSocket gratuito con mensajes AIS terrestres en tiempo real a nivel global.

- **Endpoint**: `wss://stream.aisstream.io/v0/stream`
- **Auth**: API key (registro gratuito en aisstream.io) enviada en el mensaje de suscripción.
  La key vive solo en `.env` del worker; nunca en el código, el frontend ni la documentación.
- **Suscripción**: mensaje JSON con `APIKey`, `BoundingBoxes` y `FilterMessageTypes`.

### Bounding box inicial del área del Canal

```json
{
  "APIKey": "<AISSTREAM_API_KEY>",
  "BoundingBoxes": [[[8.4, -80.2], [9.7, -79.2]]],
  "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
}
```

> Orden de AISStream: `[lat, lon]`. GeoJSON y PostGIS usan `[lon, lat]`; la conversión ocurre
> en el parser y está cubierta por tests.

La caja cubre ambas entradas y los dos fondeaderos. Se verifica y ajusta con datos reales en la
tarea 3.8.

### Mensajes relevantes

| Tipo | Contenido | Uso |
|---|---|---|
| `PositionReport` | MMSI, lat/lon, SOG, COG, heading, estado de navegación | posiciones, tránsitos, fondeo |
| `ShipStaticData` | nombre, IMO, tipo, dimensiones, destino | ficha del buque (`vessels`) |

## 2. Reglas y límites de AISStream (obligatorias)

1. **Una conexión WebSocket por API key.** Solo el proceso `worker` se conecta.
2. **No conectar desde el navegador**: la API reenvía lo necesario por `/ws/live`.
3. **Solo AIS terrestre**: cobertura hasta ~40 NM de la costa. Suficiente para el Canal.
4. **Sin histórico**: nuestra base de datos es el archivo histórico. El worker debe ser robusto.
5. **Reconexión**: backoff exponencial con jitter (1 s → máx. 60 s), loguear cada caída.
6. **Términos de uso** (revisado el 2026-10-21, tarea 3.7, ADR-0008): AISStream **no publica
   términos de uso** (`https://aisstream.io/terms` da 404; solo hay política de privacidad en
   `https://aisstream.io/privacypolicy`). Su documentación asume que el servidor reenvía los datos
   a sus clientes (*"proxy only the information each client needs"*). Sin permiso explícito para
   mostrarlos a cualquiera, **los datos solo se muestran a usuarios con sesión**: sin modo anónimo.
7. **Límites del servicio**: 3 conexiones suscritas por cuenta y 3 abiertas por IP; suscripción
   en 3 s; como mucho una actualización de suscripción por segundo; 200 MMSI por filtro. Las
   conexiones sin compresión tendrán límite de ancho de banda desde septiembre de 2026.

## 2b. Prueba con datos reales (tarea 3.8, 2026-10-21)

**Funciona**: la key, la suscripción (confirmada, con compresión) y el parser con el formato real.
Con el worker congelado 4 minutos, AISStream cerró la conexión y el worker se reconectó y volvió a
suscribirse en 2 segundos, sin intervención. La key no apareció en ningún log.

**Cobertura del Canal: casi nula.** AISStream depende de receptores terrestres de voluntarios:

| Zona (mismo cliente y cuenta) | Tiempo | Recibido |
|---|---|---|
| Róterdam / canal de la Mancha (control) | 45 s | 437 mensajes de 410 buques |
| bbox del Canal (worker real) | 3 min | 0 mensajes |
| Panamá amplia (6,5–11,5 N, 83,5–76,5 O) | 10 min | 9 mensajes de 3 buques, ninguno en el Canal |
| bbox del Canal (`scripts/ais_coverage.py`) | 2 min | 0 mensajes |

Con decenas de buques fondeados emitiendo al menos cada 3 minutos, con cobertura llegarían
cientos de mensajes cada 10 minutos. **Decisión del dueño**: medir varios días antes de decidir
(la cobertura de voluntarios varía) y, mientras, la demo usa el simulador rotulado como datos
simulados. La bbox no se ha podido ajustar con datos reales: se mantiene.

Medir la cobertura (solo recuentos, sin guardar mensajes; `data/` no se sube a git):

```bash
python scripts/ais_coverage.py --minutes 2 --output data/coverage.jsonl
```

**Formato real**, distinto del ejemplo de la documentación de AISStream (el parser solo usa
`MMSI` y `ShipName` de `MetaData`, así que no le afecta):

- `MetaData`: `MMSI`, `MMSI_String` (un entero igual a `MMSI`), `ShipName`, `latitude` y
  `longitude` **en minúsculas**, y `time_utc` como `2026-10-21 13:43:46.580659461 +0000 UTC`.
- Los textos (`ShipName`, `Name`, `Destination`) llegan rellenos con **espacios** hasta su
  longitud fija (el `@` del protocolo ya viene decodificado). El simulador y las fixtures usan
  este formato.



Polígonos GeoJSON versionados en `app/services/zones.py` (se definen en Fases 5 y 6):

| Zona | Uso |
|---|---|
| Entrada Atlántico (Limón Bay / Cristóbal) | inicio o fin de tránsito |
| Entrada Pacífico (Balboa) | inicio o fin de tránsito |
| Fondeadero Atlántico | tiempo de espera |
| Fondeadero Pacífico (Bahía de Panamá) | tiempo de espera |

Convención de dirección (la de la ACP): **southbound** = Atlántico → Pacífico,
**northbound** = Pacífico → Atlántico.

## 4. Lo que no está disponible públicamente

- Los sistemas de la Autoridad del Canal de Panamá (EVTMS, VUMPA) son de acceso restringido.
- Tarifas, reservas de tránsito y filas oficiales: sin API pública. El proyecto **infiere**
  tránsitos y esperas a partir de AIS. Esa inferencia es parte del valor del proyecto y se valida
  contra estadísticas públicas de la ACP (tarea 5.7).

## 5. Simulador para desarrollo offline

`scripts/ais_simulator.py` (tarea 3.6) genera mensajes con el formato de AISStream (todos los
campos obligatorios de su esquema OpenAPI): buques que esperan en los dos fondeaderos, cruzan el
Canal en ambos sentidos (≈ 7 h de fondeadero a fondeadero, a ~2 nudos en las esclusas) y uno que
pierde la señal a mitad de tránsito. Es reproducible: la misma `--seed` da los mismos mensajes.
Permite desarrollar, hacer demos y correr CI sin API key.

```bash
# Mensajes en JSON Lines (opcionalmente con un 5 % de mensajes inválidos para probar filtros)
python scripts/ais_simulator.py jsonl --minutes 30 --seed 7 --invalid-ratio 0.05

# Servidor WebSocket local que imita el protocolo de AISStream: suscripción en 3 s,
# `SubscriptionConfirmation`, frames binarios, `permessage-deflate` y filtros por caja, tipo y MMSI.
# --speed 60 reproduce una hora de tráfico en un minuto.
python scripts/ais_simulator.py serve --port 8765 --speed 60
```

El worker (3.3) se apunta al simulador cambiando solo la URL del WebSocket:

```bash
python scripts/ais_simulator.py serve --speed 60      # en una terminal
AISSTREAM_URL=ws://127.0.0.1:8765 AISSTREAM_API_KEY=cualquier-valor \
  python -m app.workers.ais_consumer                  # en otra
``` El servidor escucha en
`127.0.0.1`, acepta cualquier `APIKey` no vacía y no la registra: nunca uses aquí la key real.
Las coordenadas de la ruta son aproximadas y se contrastan con datos reales en la tarea 3.8.
Fixtures fijas de un mensaje en `tests/fixtures/ais_messages/`.

## 6. Otras fuentes (referencia, no usar por ahora)

| Fuente | Notas |
|---|---|
| MarineTraffic / VesselFinder | comerciales; scraping prohibido por sus términos |
| NOAA AIS histórico | cubre aguas de EE. UU., no Panamá |
| OpenSky Network | ADS-B (aviación), idea futura para Tocumen. Requiere OAuth2 client-credentials |
