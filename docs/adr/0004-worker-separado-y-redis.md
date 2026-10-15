# ADR-0004: Worker de ingesta como proceso separado y Redis pub/sub

- **Fecha**: 2026-10-15
- **Estado**: Aceptada

## Contexto
El diseño inicial ejecutaba el consumidor de AISStream dentro de la app FastAPI, comunicado por
una `asyncio.Queue`. Eso no escala: con N réplicas de la API habría N conexiones a AISStream
(viola la regla de una conexión por key) y cada réplica solo vería sus propios eventos, así que
`/ws/live` no podría servir a clientes conectados a réplicas distintas.

## Decisión
- El worker es un **proceso independiente** (`python -m app.workers.ais_consumer`), con una sola
  réplica.
- El worker persiste en PostgreSQL y **publica** cada posición procesada en Redis
  (`vessels.live`).
- Cada réplica de la API se **suscribe** a Redis y reenvía a sus clientes WebSocket.
- El estado del worker (último mensaje, reconexiones) se guarda en Redis para el endpoint admin.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Worker dentro de la API | no escala horizontalmente (ver contexto) |
| PostgreSQL LISTEN/NOTIFY | válido a bajo volumen, pero acopla el tiempo real a la DB y tiene límite de payload |
| Kafka / RabbitMQ | sobredimensionado para el volumen del Canal; más infra que mantener |
| Redis Streams | opción futura si se necesita reprocesar eventos; pub/sub basta para fan-out en vivo |

## Consecuencias
- Un servicio más en Docker Compose (`redis`).
- La API es sin estado y escalable; el worker es un punto único que debe reiniciarse solo y
  vigilarse con métricas y alertas.
- Pub/sub no guarda mensajes: si una réplica se desconecta, el cliente recupera con el snapshot.
