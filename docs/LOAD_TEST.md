# Prueba de carga de `/ws/live` (tarea 4.8)

Comprueba que el WebSocket aguanta 500 clientes simultáneos y que la ingesta AIS no se degrada
mientras tanto.

## Resultado

| Medida | Valor |
|---|---|
| Clientes pedidos / conectados / con snapshot | 500 / 500 / 500 |
| Fallos de conexión o cierres inesperados | 0 |
| Tiempo hasta el primer snapshot (p50 / p95 / máx) | 9 ms / 11 ms / 37 ms |
| Intervalo entre mensajes por cliente (p50 / p95 / máx) | 2,00 s / 2,00 s / 3,01 s |
| Mensajes recibidos en total | 17 466 |
| CPU del proceso de la API (media / máx) | 7,8 % / 10,9 % |
| Memoria de la API (máx) | 153 MB |
| Ingesta sin clientes | 10,63 filas/s |
| Ingesta con los 500 clientes conectados | 9,52 filas/s |

**Conclusión**: el WebSocket cumple el objetivo de la fase con 500 clientes. La ingesta bajó un
10 % entre las dos mediciones, pero eso entra en la variación normal del simulador: cuatro
ventanas de 20 s sin ningún cliente midieron 10,67, 10,38, 8,98 y 10,58 filas/s. No hay una
degradación atribuible al WebSocket.

## Cómo se midió

- **Entorno**: un solo equipo (Apple M5, 10 núcleos, 16 GB). PostgreSQL y Redis en contenedores
  (`docker compose up -d --wait`); API (`uvicorn`, un solo worker), worker AIS y simulador en el
  host. Cliente y servidor comparten máquina y red de loopback, así que no se mide latencia de red.
- **Tráfico**: el simulador de `scripts/ais_simulator.py` (`--speed 60`) como fuente AIS. Con los
  clientes conectados, la API recibe las posiciones por Redis y las reenvía filtradas por viewport.
- **Clientes**: `scripts/ws_load_test.py`. Cada uno se autentica en el primer mensaje, se suscribe
  al bbox del Canal y lee mensajes durante 60 s. Se abrieron en una rampa de 20 s.
- **Usuarios**: la API limita a 5 conexiones por usuario, así que 500 clientes son 100 usuarios
  de prueba con 5 sockets cada uno. El límite no se tocó. El script crea los usuarios en la base
  y acuña sus access tokens sin pasar por `/auth/login` (tiene límite por IP y la prueba mide el
  WebSocket, no el login). Los borra al terminar.
- **Ingesta**: filas nuevas por segundo en `positions`, 20 s antes de abrir clientes y durante
  toda la prueba.

## Límites de esta prueba

- Un solo equipo y una sola réplica de la API. No dice cómo se comporta con varias réplicas ni
  con latencia de red real.
- El simulador emite unas 10 posiciones por segundo en el área del Canal. Con tráfico real
  (mucho mayor en horas punta) el reenvío por cliente sería más pesado; conviene repetir la
  prueba con la API key real antes de dar el resultado por definitivo.
- El intervalo de 2 s entre mensajes lo marca el tráfico del simulador (solo se envía lo que
  cambió), no el batching de 1 Hz del servidor.

## Cómo repetirla

```bash
docker compose up -d --wait
export AISSTREAM_URL=ws://127.0.0.1:8765 AISSTREAM_API_KEY=simulator
python scripts/ais_simulator.py serve --port 8765 --speed 60 &
python -m app.workers.ais_consumer &
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
python scripts/ws_load_test.py --clients 500 --duration 60 --api-pid $(pgrep -f "uvicorn app.main")
```
