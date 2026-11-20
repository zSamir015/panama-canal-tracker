# Worker AIS continuo en macOS (`launchd` + `caffeinate`)

Guía para mantener `app.workers.ais_consumer` estable en segundo plano en un Mac, reiniciándose
solo si falla o al iniciar sesión, y evitando el reposo mientras esté conectado a corriente AC.

## Qué resuelve

- Arranque automático al iniciar sesión en macOS (`RunAtLoad`) y reinicio con pausa mínima de 15 s
  (`KeepAlive` + `ThrottleInterval`) si el proceso se cae o tras reiniciar Docker / el Mac.
- Ejecución envuelta en `caffeinate -i -s`:
  - `-i` evita reposo por inactividad de usuario.
  - `-s` impide la suspensión del sistema **solo mientras el Mac está enchufado a corriente AC**
    (en batería respeta el ahorro de energía habitual).
  - La pantalla sí puede apagarse normalmente.

> **Aviso sobre tapa cerrada**: en portátiles MacBook, cerrar la tapa sigue suspendiendo el equipo
> salvo que tenga un monitor externo conectado en modo *clamshell* (enchufado a corriente).

## Requisitos previos

1. PostgreSQL + TimescaleDB y Redis corriendo (por ejemplo `docker compose up -d db redis`).
2. Entorno `.venv` creado con las dependencias instaladas.
3. Fichero `.env` en la raíz del repositorio con tu `AISSTREAM_API_KEY` real (`AISSTREAM_URL`,
   `DATABASE_URL` y `REDIS_URL`).
   - **Convivencia con GitHub Actions (`ADR-0019`)**: el recolector (`collect-ais.yml`) y el worker
     local pueden ejecutarse **a la vez solo con `AIS_CANAL_BOUND_ENABLED=false`** en el worker
     (`1` conexión worker + `1` recolector = `2` máximo). El script
     `scripts/macos/run_worker_caffeinate.sh` fija explícitamente `AIS_CANAL_BOUND_ENABLED=false`
     al arrancar.

## Instalación y gestión

Desde la raíz del repositorio:

```bash
# Instalar (o actualizar) y arrancar el LaunchAgent
./scripts/macos/install_launchd_worker.sh

# Comprobar estado y últimas líneas del log
./scripts/macos/install_launchd_worker.sh --status

# Parar y eliminar el agente
./scripts/macos/install_launchd_worker.sh --uninstall
```

Los logs quedan fuera del repositorio en:
- `~/Library/Logs/panama-canal-tracker/worker.out.log`
- `~/Library/Logs/panama-canal-tracker/worker.err.log`
