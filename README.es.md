# Panama Canal Tracker

> Seguimiento en tiempo real de los buques que cruzan el Canal de Panamá: ingesta AIS Clase A/B en
> vivo, detección automática de tránsitos y esperas en fondeo, mapa satelital/vectorial y analítica.

[English](README.md)

[![CI](https://github.com/zSamir015/panama-canal-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/zSamir015/panama-canal-tracker/actions/workflows/ci.yml)
[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-yellow.svg)](LICENSE)

**[Demo en vivo](https://zsamir015.github.io/panama-canal-tracker/)**: corre directo en el navegador
con trayectorias simuladas sobre el eje real del Canal (también accesible desde «Ver demo sin
cuenta» en el login, sin backend ni API key).

![Recorrido visual operativo: vista clara del Canal, buscador global, tooltip, satélite oscuro y estadísticas KPI](docs/media/live-map.gif)

---

## Recorrido visual y capacidades principales

### Navegación en tiempo real (Consola OLED Oscura + Satélite Esri)
Todas las trayectorias del simulador y la demo siguen el cauce navegable real de OpenStreetMap por
Bahía Limón, Esclusas de Gatún, Lago Gatún, Corte Culebra y Balboa sin cruzar tierra. Las siluetas
navales direccionales con puente blanco se combinan con balizas compactas en fondeaderos y escala
adaptativa según el zoom.

![Buques navegando de forma fluida por Lago Gatún y Corte Culebra sobre imagen satelital Esri](docs/media/live-motion.gif)

### Galería de funcionalidades

| Mapa claro y barra operativa de escritorio | Modo oscuro OLED y capa satelital |
| :---: | :---: |
| ![Mapa de escritorio en tema claro con 18 buques, KPIs y leyenda interactiva](docs/media/ui-desktop-light-map.png) | ![Vista satelital oscura con casco del buque, estela de 30 min, copiar MMSI y hora de Panamá](docs/media/ui-desktop-dark-satellite.png) |
| *Flota de 18 buques en vivo, KPIs operativos en barra lateral, filtros por tipo y leyenda interactiva* | *Esri World Imagery (`ADR-0018`), tema oscuro OLED, estela de 30 min, «Copiar MMSI» y hora `America/Panama`* |

| Buscador global (`/`, `⌘K`) y progreso de tránsito | Tooltip de escritorio y escala según zoom |
| :---: | :---: |
| ![Buscador global en cabecera y barras de progreso de tránsitos con sentido](docs/media/ui-desktop-search-transits.png) | ![Tooltip al pasar el cursor sobre el buque mostrando nombre, tipo y velocidad](docs/media/ui-desktop-hover-tooltip.png) |
| *Buscador por nombre, MMSI o IMO, estado sincronizado en URL (`?mmsi=&view=`) y progreso estimado sobre la mediana* | *Tooltip de escritorio (`nombre · tipo · velocidad`), atenuación de señal antigua (>15 min) y balizas compactas* |

| Estadísticas del Canal (`?view=stats`) | Vista móvil (`390×844`) y hoja arrastrable |
| :---: | :---: |
| ![Vista de estadísticas con KPIs superiores, comparativa frente al periodo anterior y aviso de cobertura AIS](docs/media/ui-desktop-stats-kpis.png) | ![Vista móvil responsiva oscura con hoja inferior expandida y arrastrable](docs/media/ui-mobile-sheet.png) |
| *Tarjetas KPI con variación vs periodo anterior, aviso honesto de cobertura AIS parcial y barras apiladas por sentido* | *Corrección `100dvh` para iOS Safari, cabecera compacta y hoja inferior táctil arrastrable (`useSheetDrag`)* |

---

## Qué hace

- 📡 **Ingiere** mensajes AIS Clase A y Clase B (`PositionReport`, `StandardClassBPositionReport`,
  `ExtendedClassBPositionReport`, `StaticDataReport` y `ShipStaticData`) desde
  [AISStream.io](https://aisstream.io) con volcado por lotes y difusión WebSocket cada `0,5 s`
- 🗺️ **Muestra** todos los buques en una sola capa WebGL GeoJSON (React + MapLibre GL) con cascos
  navales direccionales, capas **Estándar / Satélite**, tema claro/oscuro (`prefers-color-scheme`)
  y atenuación de señales antiguas
- 🔍 **Detecta** tránsitos completos (Atlántico ↔ Pacífico) con sentido (`↓`/`↑`), barra de progreso
  estimada, duración y medianas históricas
- ⏱️ **Mide** esperas en los fondeaderos Atlántico y Pacífico antes de entrar al Canal
- 📊 **Expone** analítica REST y flujo WebSocket en vivo sobre TimescaleDB + PostGIS
- ♿ **UX y accesibilidad**: pestañas WAI-ARIA (`tablist`/`tab`) con flechas, gestión automática de
  foco en fichas, buscador `/` y `⌘K`, URL compartible, conmutador de contraseña, botones `Reintentar`
  en español y tipografía monoespaciada tabular (`--font-mono`)
- 🔐 **Seguridad endurecida**: JWT con rotación de refresh cookies HttpOnly (`Argon2id`), CSP estricto
  y regla ESLint que prohíbe `dangerouslySetInnerHTML`

No existe una API pública oficial con los tránsitos del Canal. Este proyecto **infiere** tránsitos y
esperas desde señales AIS y comunica de forma transparente la cobertura terrestre parcial tanto en
estados vacíos como en estadísticas.

## Arquitectura

```mermaid
flowchart LR
    AIS["AISStream.io / Simulador"] -->|WebSocket| W["Worker de ingesta"]
    W -->|"batch 0,5 s"| DB[("PostgreSQL + PostGIS + TimescaleDB")]
    W -->|"publish"| R[("Redis Pub/Sub")]
    R -->|"push 0,5 s"| API["FastAPI · N réplicas"]
    DB --> API
    API -->|"REST + WebSocket"| WEB["React + TypeScript + MapLibre GL"]
```

El worker y la API son procesos independientes: la API escala horizontalmente manteniendo una única
conexión AIS aguas arriba. Detalles en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Stack técnico y calidad

| Capa | Tecnología y verificación |
|---|---|
| API y Auth | Python 3.12, FastAPI (async), Pydantic v2, PyJWT, `pwdlib` (Argon2id) |
| Datos y Geo | PostgreSQL 16, PostGIS, TimescaleDB, SQLAlchemy 2.0 async, Alembic |
| Tiempo real | Worker WebSocket AIS Clase A/B (`0,5 s`), Redis pub/sub, `/ws/live` |
| Frontend | React 19, TypeScript estricto, Vite, MapLibre GL JS (WebGL), TanStack Query |
| Calidad | **788** tests unitarios backend (`pytest -m "not integration"`), **247** tests frontend (`Vitest`), `mypy --strict`, `ruff`, `eslint --max-warnings=0`, `pip-audit`, `gitleaks` |
| Operación | Docker Compose endurecido (no-root), GitHub Actions (7 checks CI), métricas Prometheus |

## Estado del proyecto

| Fase | Alcance | Estado |
|---|---|---|
| 0 | Scaffold y documentación | ✅ |
| 1 | Esqueleto FastAPI, CI, seguridad del repo | ✅ |
| 2 | Base de datos y autenticación | ✅ |
| 3 | Worker de ingesta AIS | ✅ |
| 4 | Mapa en tiempo real y demo | ✅ |
| 5 | Detección de tránsitos y validación | ✅ |
| 6 | Esperas en fondeo y estadísticas | ✅ |
| 7 | Endurecimiento para producción y mejoras UI/UX | ✅ / ⏳ (sin despliegue productivo gestionado según [ADR-0017](docs/adr/0017-v1-sin-entorno-de-produccion.md)) |

Las fases 5 y 6 están cerradas. La validación con 12,5 días de datos reales en
[docs/VALIDATION.md](docs/VALIDATION.md) confirma que la cobertura gratuita de AISStream dentro del
Canal es parcial, por lo que los umbrales y polígonos siguen calibrados sobre trayectorias
sintéticas alineadas con OpenStreetMap.

Plan completo: [docs/ROADMAP.md](docs/ROADMAP.md).

## Inicio rápido

Toda la pila (PostgreSQL, Redis, migraciones, API, worker AIS y simulador de 18 buques a velocidad
`2×`) corre en contenedores sin API key:

```bash
cp .env.example .env            # contraseñas aleatorias y JWT_SECRET_KEY; nunca commitear .env
AISSTREAM_URL=ws://simulator:8765 AISSTREAM_API_KEY=simulator \
  docker compose -f docker-compose.stack.yml --profile simulator up -d --build --wait
# Documentación de la API: http://localhost:8000/docs (registro, login y GET /api/v1/vessels)
docker compose -f docker-compose.stack.yml --profile simulator down   # parar (-v borra los datos)
```

Con una clave real de AISStream.io, añádela en `AISSTREAM_API_KEY` dentro de `.env` y omite las
variables y el perfil `--profile simulator`. Para desarrollo local con `--reload`, consulta
[AGENTS.md](AGENTS.md#10-comandos-útiles).

## Documentación

| Documento | Contenido |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Componentes, flujo de datos y modelo de datos |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Fases y criterios de aceptación |
| [docs/API_DESIGN.md](docs/API_DESIGN.md) | Contrato REST y WebSocket |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Fuente AIS, límites y zonas geográficas |
| [docs/LOAD_TEST.md](docs/LOAD_TEST.md) | Prueba de carga WebSocket (500 clientes) |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Estudio de 12,5 días de cobertura AIS real |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Revisión de seguridad y requisitos previos a producción |
| [docs/adr/](docs/adr/) | Architecture Decision Records ([0001](docs/adr/0001-stack-tecnico.md)–[0018](docs/adr/0018-satelite-esri-world-imagery.md)) |
| [AGENTS.md](AGENTS.md) | Convenciones de ingeniería y seguridad |
| [SECURITY.md](SECURITY.md) | Cómo reportar una vulnerabilidad |

## Licencia

[MIT](LICENSE)
