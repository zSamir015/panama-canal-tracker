# Panama Canal Tracker

Vessel tracking for the Panama Canal built on live AIS data: it ingests the AIS stream, infers canal
transits and anchorage waits, and shows them on a real-time map with statistics and history.

[Español](README.es.md)

[![CI](https://github.com/zSamir015/panama-canal-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/zSamir015/panama-canal-tracker/actions/workflows/ci.yml)
[![License: All rights reserved](https://img.shields.io/badge/License-All%20rights%20reserved-red.svg)](LICENSE)

[Live demo](https://zsamir015.github.io/panama-canal-tracker/): the static demo runs in the browser
on simulated vessels that follow the real fairway, or through **Ver demo sin cuenta** on the login
screen. It needs no API key and no backend.

![Walkthrough of the interface: light canal view, global search, hover tooltip, dark satellite view and statistics](docs/media/live-map.gif)

## Overview

There is no public source of official Canal transit data. This project infers transits and
anchorage waits from raw AIS signals and says plainly where that inference stops: free terrestrial
AIS coverage inside the Canal is partial, so most of the fairway has no signal (see
[Data and limitations](#data-and-limitations)).

The system has three parts:

- An ingestion worker that reads AIS from [AISStream.io](https://aisstream.io), validates and stores
  positions, and runs the transit and anchorage detectors.
- A FastAPI service that exposes REST endpoints and a WebSocket with the live positions.
- A React and MapLibre frontend with the live map, a transit panel, statistics and a history view.

## Status

The project is complete. Phases 0 to 7 of the [roadmap](docs/ROADMAP.md) are closed and `v1.0.0`
was released on 2026-11-20. Changes after the release are small improvements to the interface and
the tooling, listed under *Unreleased* in the [changelog](CHANGELOG.md).

Two scope decisions are deliberate:

- There is no production environment ([ADR-0017](docs/adr/0017-v1-sin-entorno-de-produccion.md)).
  It runs as a local `docker compose` stack plus a static demo on GitHub Pages. What a public
  deployment would still need is listed in [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md).
- AISStream data is not shown to anonymous visitors
  ([ADR-0008](docs/adr/0008-demo-con-login.md)): the map requires an account, and the public demo
  uses simulated data.

## Screenshots

### Interface, with simulated data

| Light map and sidebar | Dark theme and satellite layer |
| :---: | :---: |
| ![Light map with 18 vessels, fleet figures and a filterable legend](docs/media/ui-desktop-light-map.png) | ![Dark satellite view with a selected vessel, its 30-minute trail and the Panama time zone](docs/media/ui-desktop-dark-satellite.png) |
| Fleet figures, filters by vessel type and an interactive legend. | Esri World Imagery ([ADR-0018](docs/adr/0018-satelite-esri-world-imagery.md)), dark theme, the last 30 minutes of the trail and times in `America/Panama`. |

| Search and transit progress | Hover tooltip |
| :---: | :---: |
| ![Header search dropdown and transit progress bars with direction](docs/media/ui-desktop-search-transits.png) | ![Tooltip over a vessel showing name, type and speed](docs/media/ui-desktop-hover-tooltip.png) |
| Search by name, MMSI or IMO (`/` or `⌘K`), a shareable URL (`?mmsi=&view=`) and progress estimated against the median transit. | Name, type and speed on hover; signals older than 15 minutes fade. |

| Statistics (`?view=stats`) | Mobile layout (`390×844`) |
| :---: | :---: |
| ![Statistics view with period figures, comparison with the previous period and the coverage notice](docs/media/ui-desktop-stats-kpis.png) | ![Mobile dark layout with an expanded bottom sheet](docs/media/ui-mobile-sheet.png) |
| Figures for the period against the previous one, a notice about partial AIS coverage and daily bars by direction. | Compact header and a bottom sheet that can be dragged. |

### History and routes, with simulated data

| History (`?view=history`) | Route window |
| :---: | :---: |
| ![History tab listing the vessels seen in the last 48 hours](docs/media/ui-desktop-history.png) | ![Dark map with the 7-day route of a vessel and the window selector on its card](docs/media/ui-desktop-trail-7d.png) |
| Vessels with a position in the last 24 h, 48 h, 7 or 30 days, newest first, with a filter by name, MMSI or IMO. Choosing one opens it on the map. | The vessel card offers 30 min, 6 h, 24 h, 48 h and 7 days. The line joins only positions that were received and breaks at long gaps in signal. |

The History tab needs the API, so the static demo does not include it. The screenshots above use
simulated vessels with fictitious names.

### With real AIS data

| History, last 48 hours | 7-day route of a cargo ship |
| :---: | :---: |
| ![History with real vessels from the last 48 hours; personal vessels are masked](docs/media/real-ais-history-48h.png) | ![Real 7-day route of a cargo ship arriving at the Pacific anchorage](docs/media/real-ais-route-7d.png) |
| 117 real vessels. Sailing, pleasure and fishing vessels are masked because their name and MMSI can identify a person. | A cargo ship approaching the Pacific anchorage from the south-east. Only commercial vessels are shown with a route. |

Real data from [AISStream.io](https://aisstream.io), collected between 2026-11-07 and 2026-11-22
by the local worker and the GitHub collector. Coverage is partial, so the picture is sparse. These
are static images ([ADR-0020](docs/adr/0020-capturas-con-datos-reales.md)).

## Features

- Ingestion of Class A and Class B AIS messages from AISStream, written in batches every 0.5 s and
  published through Redis to the WebSocket.
- Real-time map with vessels in a single WebGL layer, vector and satellite basemaps, light and dark
  themes, and filtering by vessel type.
- Detection of complete transits between the Atlantic and Pacific entrances, with direction, estimated
  progress and elapsed time ([ADR-0016](docs/adr/0016-sentido-de-entrada-por-rumbo.md)).
- Measurement of waiting time at the Atlantic and Pacific anchorages before entering.
- Statistics by period, and a history view with a selectable route window of up to 7 days.
- Search by name, MMSI or IMO, and state kept in the URL.
- Accessible controls: arrow-key navigation between views, managed focus in panels and visible
  keyboard focus.
- Authentication with short-lived access tokens and rotating refresh tokens in an `HttpOnly`
  cookie, a strict Content Security Policy, and a lint rule that forbids inserting HTML.

## Architecture

```mermaid
flowchart LR
    AIS["AISStream.io or simulator"] -->|WebSocket| W["Ingestion worker"]
    W -->|"batch insert, 0.5 s"| DB[("PostgreSQL, PostGIS, TimescaleDB")]
    W -->|publish| R[("Redis pub/sub")]
    R -->|"push, 0.5 s"| API["FastAPI"]
    DB --> API
    API -->|"REST and WebSocket"| WEB["React, TypeScript, MapLibre GL"]
```

The worker and the API are separate processes ([ADR-0004](docs/adr/0004-worker-separado-y-redis.md)),
so the API can scale without opening more connections to AISStream; the worker is a single
instance by design. Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Technology and quality

| Layer | Technology |
|---|---|
| API and authentication | Python 3.12, FastAPI (async), Pydantic v2, PyJWT, `pwdlib` (Argon2id) |
| Data | PostgreSQL 16, PostGIS, TimescaleDB, SQLAlchemy 2.0 async, Alembic |
| Real time | AISStream WebSocket worker, Redis pub/sub, `/ws/live` |
| Frontend | React 19, TypeScript (strict), Vite, MapLibre GL JS, TanStack Query |
| Operations | Docker Compose with non-root, read-only containers, GitHub Actions, Prometheus `/metrics` |

Checks run in CI on every pull request and must pass before merging: 1,147 backend tests
(unit and integration against real PostgreSQL and Redis), 274 frontend tests, `mypy --strict`,
`ruff`, `eslint --max-warnings=0`, `pip-audit`, `npm audit`, `gitleaks`, and a container build.

## Data and limitations

[docs/VALIDATION.md](docs/VALIDATION.md) compares the detector with real AIS over 14.9 days
(2026-11-07 to 2026-11-21):

- The collector listened for 201.4 of 356.4 hours (56.5%) and recorded 10,040 positions from 595
  vessels.
- Only 86 positions (0.9%) fell inside the entrance zones, and 26 inside the Canal corridor.
- The detector completed 2 transits, against roughly 520 expected from the Canal Authority's
  average of about 35 a day.

That gap measures AISStream coverage in Panama, not the accuracy of the detector, and the study
concludes that the data does not allow the thresholds to be calibrated. The transit and anchorage
logic is verified with the simulator and synthetic trajectories. The live map therefore shows few
vessels, and the statistics only count completed transits, so they are mostly empty.

A WebSocket load test with 500 concurrent clients ([docs/LOAD_TEST.md](docs/LOAD_TEST.md)) connected
all of them with no failures and a median snapshot latency of 9 ms (95th percentile 11 ms). Ingestion
kept running under load: 9.5 rows/s against a baseline of 10.6.

## Running it

The full stack (PostgreSQL, Redis, migrations, API, worker and a simulator with 18 vessels) runs in
containers with no external API key:

```bash
cp .env.example .env            # fill in random passwords and JWT_SECRET_KEY; never commit .env
AISSTREAM_URL=ws://simulator:8765 AISSTREAM_API_KEY=simulator \
  docker compose -f docker-compose.stack.yml --profile simulator up -d --build --wait
# API documentation: http://localhost:8000/docs (register, log in, then GET /api/v1/vessels)
docker compose -f docker-compose.stack.yml --profile simulator down   # stop; add -v to wipe data
```

With a real key from AISStream, set `AISSTREAM_API_KEY` in `.env` and leave out the simulator
variables and profile. For development on the host, backups, the macOS worker and loading collected
data, see [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Documentation

[docs/README.md](docs/README.md) is the index. The main documents:

| Document | Content |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, data model and domain logic |
| [docs/API_DESIGN.md](docs/API_DESIGN.md) | REST and WebSocket contract |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Running, checking and maintaining the system |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Study with real AIS: what it can and cannot conclude |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Final security review and what a deployment would need |
| [docs/adr/](docs/adr/README.md) | Architecture decisions ([0001](docs/adr/0001-stack-tecnico.md) to [0020](docs/adr/0020-capturas-con-datos-reales.md)) |
| [AGENTS.md](AGENTS.md) | Conventions for code, tests, security and workflow |

This README is available in English and Spanish; the rest of the documentation is in Spanish.

## Development process

Each change is one issue, one branch and one pull request, with architecture decisions recorded as
ADRs and a changelog entry per release. History: [issues](https://github.com/zSamir015/panama-canal-tracker/issues),
[merged pull requests](https://github.com/zSamir015/panama-canal-tracker/pulls?q=is%3Apr+is%3Amerged),
[releases](https://github.com/zSamir015/panama-canal-tracker/releases) and the
[changelog](CHANGELOG.md).

## Security

See [SECURITY.md](SECURITY.md) to report a vulnerability and
[docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) for the review.

## License

All rights reserved. The code is public so that it can be read and evaluated; using, copying or
modifying it requires written permission. See [LICENSE](LICENSE).
