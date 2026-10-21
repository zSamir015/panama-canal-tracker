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
6. **Términos de uso**: pendiente revisar si permiten mostrar los datos en una demo pública y
   con qué condiciones (tarea 3.7). Documentar aquí la conclusión con enlace a la fuente.

## 3. Zonas geográficas

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

El worker (3.3) se apunta al simulador cambiando solo la URL del WebSocket. El servidor escucha en
`127.0.0.1`, acepta cualquier `APIKey` no vacía y no la registra: nunca uses aquí la key real.
Las coordenadas de la ruta son aproximadas y se contrastan con datos reales en la tarea 3.8.
Fixtures fijas de un mensaje en `tests/fixtures/ais_messages/`.

## 6. Otras fuentes (referencia, no usar por ahora)

| Fuente | Notas |
|---|---|
| MarineTraffic / VesselFinder | comerciales; scraping prohibido por sus términos |
| NOAA AIS histórico | cubre aguas de EE. UU., no Panamá |
| OpenSky Network | ADS-B (aviación), idea futura para Tocumen. Requiere OAuth2 client-credentials |
