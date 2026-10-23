# Imágenes de la API y del worker AIS (tarea 3.10). Un solo Dockerfile, dos imágenes finales:
#
#   docker build --target api    -t panama-canal-tracker/api .
#   docker build --target worker -t panama-canal-tracker/worker .
#
# - Base fijada por versión y digest (índice multi-arquitectura: amd64 y arm64).
# - Dependencias solo desde requirements.lock, con hashes: la misma instalación siempre.
# - Sin secretos en ninguna capa: ni ARG ni ENV con credenciales; todo llega por entorno al
#   arrancar el contenedor (AGENTS.md §8.1). `.dockerignore` deja fuera `.env`, tests y docs.
# - Se ejecuta como un usuario sin privilegios.

ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

# --- Etapa de construcción: el entorno virtual con las dependencias ---------------------------
FROM ${PYTHON_IMAGE} AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
COPY requirements.lock /tmp/requirements.lock
# Solo dependencias de producción (sin pytest, ruff...). El proyecto no se instala con
# `pip install .`: eso descargaría el backend de build sin verificar su hash.
RUN /opt/venv/bin/pip install --require-hashes --no-deps -r /tmp/requirements.lock

# --- Base común de las imágenes finales --------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

RUN groupadd --system --gid 10001 canal \
    && useradd --system --uid 10001 --gid canal --no-create-home --shell /usr/sbin/nologin canal

COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
# El código, propiedad de root y de solo lectura para el usuario que lo ejecuta.
COPY app/ app/
COPY scripts/ scripts/

USER 10001:10001

# --- API -------------------------------------------------------------------------------------
FROM runtime AS api

# Migraciones (las ejecuta el servicio `migrate` con el rol canal_owner, nunca la API).
COPY alembic.ini alembic.ini
COPY alembic/ alembic/

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# --proxy-headers: detrás del reverse proxy, uvicorn toma la IP real de X-Forwarded-For solo si
# la conexión viene de FORWARDED_ALLOW_IPS (por defecto, 127.0.0.1 y ::1).
# Sin cabecera `server: uvicorn` (no anunciar el software). Los logs salen en JSON: la app
# reconfigura los de uvicorn al arrancar (app/core/logging.py).
# --ws-max-size: uvicorn corta los frames de más de 8 KB antes de leerlos; `/ws/live` además
# rechaza los mensajes del cliente de más de 4 KB.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header", "--ws-max-size", "8192"]

# --- Worker AIS ------------------------------------------------------------------------------
FROM runtime AS worker

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "app.workers.healthcheck"]
CMD ["python", "-m", "app.workers.ais_consumer"]
