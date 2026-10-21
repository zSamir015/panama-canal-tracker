"""Simulador de tráfico AIS del Canal de Panamá con el formato de AISStream (tarea 3.6).

Genera mensajes `PositionReport` y `ShipStaticData` idénticos en forma a los de AISStream para
desarrollar, probar y hacer demos sin API key (docs/DATA_SOURCES.md §5):

- buques que cruzan el Canal hacia el Pacífico (southbound) y hacia el Atlántico (northbound),
  con velocidades realistas por tramo (lentos en las esclusas);
- buques fondeados esperando turno en los dos fondeaderos;
- un buque que pierde la señal a mitad de tránsito;
- opcionalmente, mensajes inválidos (MMSI, posición, JSON roto...) para probar los filtros.

Todo es reproducible: la misma semilla produce exactamente los mismos mensajes.

Uso:

    # Mensajes en JSON Lines por la salida estándar (fixtures, pruebas rápidas)
    python scripts/ais_simulator.py jsonl --minutes 30 --seed 7 > /ruta/temporal/ais.jsonl

    # Servidor WebSocket local que imita a AISStream (para el worker de la 3.3)
    python scripts/ais_simulator.py serve --port 8765 --speed 60

El servidor solo escucha en 127.0.0.1 por defecto, acepta cualquier `APIKey` no vacía y nunca la
registra: no pongas aquí una key real.
"""

import argparse
import asyncio
import itertools
import json
import math
import random
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

NAUTICAL_MILE_KM = 1.852
EARTH_RADIUS_KM = 6371.0088

# Intervalos de emisión (ITU-R M.1371): cada pocos segundos en marcha, cada 3 min fondeado,
# datos estáticos cada 6 min. Se usan valores algo más espaciados para no generar ruido inútil.
UNDERWAY_INTERVAL = timedelta(seconds=30)
ANCHORED_INTERVAL = timedelta(minutes=3)
STATIC_INTERVAL = timedelta(minutes=6)

MAX_MINUTES = 24 * 60
MAX_SPEED = 3600
SUBSCRIPTION_TIMEOUT_SECONDS = 3.0  # AISStream cierra si la suscripción no llega en 3 s
MAX_SUBSCRIPTION_BYTES = 16 * 1024
MAX_FILTERED_MMSI = 200

NAV_UNDERWAY = 0
NAV_AT_ANCHOR = 1

Scenario = Literal[
    "southbound", "northbound", "anchored_atlantic", "anchored_pacific", "signal_loss"
]
MessageKind = Literal["position", "static", "invalid"]


@dataclass(frozen=True, slots=True)
class Waypoint:
    name: str
    lat: float
    lon: float
    # Velocidad (nudos) en el tramo que empieza en este punto.
    speed_kn: float


# Ruta de tránsito de Atlántico a Pacífico. Coordenadas aproximadas sobre el canal navegable;
# se contrastan con datos reales en la tarea 3.8. Todas caen dentro de la bbox de AISStream.
ROUTE: tuple[Waypoint, ...] = (
    Waypoint("Fondeadero Atlántico", 9.420, -79.870, 6.0),
    Waypoint("Rompeolas de Cristóbal", 9.390, -79.918, 8.0),
    Waypoint("Esclusas de Gatún (entrada)", 9.282, -79.921, 2.0),
    Waypoint("Esclusas de Gatún (salida)", 9.262, -79.913, 8.0),
    Waypoint("Lago Gatún", 9.235, -79.880, 9.0),
    Waypoint("Lago Gatún (canal central)", 9.170, -79.835, 9.0),
    Waypoint("Gamboa", 9.115, -79.700, 6.0),
    Waypoint("Corte Culebra", 9.060, -79.655, 6.0),
    Waypoint("Esclusa de Pedro Miguel (entrada)", 9.018, -79.613, 2.0),
    Waypoint("Esclusa de Pedro Miguel (salida)", 9.013, -79.608, 5.0),
    Waypoint("Esclusas de Miraflores (entrada)", 9.003, -79.596, 2.0),
    Waypoint("Esclusas de Miraflores (salida)", 8.995, -79.590, 8.0),
    Waypoint("Balboa", 8.955, -79.567, 8.0),
    Waypoint("Puente de las Américas", 8.938, -79.558, 6.0),
    Waypoint("Fondeadero Pacífico", 8.880, -79.520, 0.0),
)

ATLANTIC_ANCHORAGE = (ROUTE[0].lat, ROUTE[0].lon)
PACIFIC_ANCHORAGE = (ROUTE[-1].lat, ROUTE[-1].lon)
ANCHORAGE_RADIUS_DEG = 0.01  # ~1 km: los buques se reparten por el fondeadero


@dataclass(frozen=True, slots=True)
class SimulatedVessel:
    mmsi: int
    name: str
    call_sign: str
    imo: int
    ship_type: int
    length_m: int
    beam_m: int
    draught_m: float
    scenario: Scenario
    # Tiempo que lleva el buque en su escenario cuando empieza la simulación: así no todos
    # aparecen en el fondeadero a la vez.
    elapsed_at_start: timedelta


# Flota sintética: MMSI con MID reales (352/353 Panamá, 636 Liberia, 538 Islas Marshall...) y
# números finales evidentes; nombres inventados.
DEFAULT_FLEET: tuple[SimulatedVessel, ...] = (
    SimulatedVessel(
        352000001,
        "PACIFIC STAR",
        "3EAA1",
        9100001,
        70,
        225,
        32,
        12.1,
        "southbound",
        timedelta(hours=0),
    ),
    SimulatedVessel(
        636000002,
        "ATLANTIC DAWN",
        "D5AA2",
        9100002,
        80,
        183,
        32,
        10.4,
        "northbound",
        timedelta(hours=1),
    ),
    SimulatedVessel(
        538000003,
        "GATUN TRADER",
        "V7AA3",
        9100003,
        70,
        294,
        49,
        13.8,
        "southbound",
        timedelta(hours=3, minutes=30),
    ),
    SimulatedVessel(
        353000004,
        "CULEBRA SPIRIT",
        "3EAA4",
        9100004,
        84,
        299,
        49,
        11.9,
        "northbound",
        timedelta(hours=4),
    ),
    SimulatedVessel(
        371000005,
        "COLON BREEZE",
        "3EAA5",
        9100005,
        70,
        199,
        32,
        11.2,
        "anchored_atlantic",
        timedelta(0),
    ),
    SimulatedVessel(
        563000006,
        "BALBOA GRACE",
        "9VAA6",
        9100006,
        80,
        249,
        44,
        12.7,
        "anchored_pacific",
        timedelta(0),
    ),
    SimulatedVessel(
        477000007,
        "MIRAFLORES SEA",
        "VRAA7",
        9100007,
        70,
        230,
        32,
        11.5,
        "anchored_pacific",
        timedelta(0),
    ),
    SimulatedVessel(
        357000008,
        "SILENT ROVER",
        "3EAA8",
        9100008,
        70,
        190,
        30,
        10.9,
        "signal_loss",
        timedelta(hours=1, minutes=30),
    ),
)

# Ventana sin señal del escenario `signal_loss`, relativa al inicio de la simulación.
SIGNAL_LOSS_WINDOW = (timedelta(minutes=10), timedelta(minutes=40))


@dataclass(frozen=True, slots=True)
class SimulatedMessage:
    at: datetime
    mmsi: int
    kind: MessageKind
    raw: str
    # Solo para `kind="invalid"`: el motivo con el que el parser debe rechazarlo.
    expected_reason: str | None = None
    lat: float | None = None
    lon: float | None = None

    @property
    def message_type(self) -> str:
        return "ShipStaticData" if self.kind == "static" else "PositionReport"


@dataclass(frozen=True, slots=True)
class _Fix:
    lat: float
    lon: float
    sog: float
    cog: float
    nav_status: int
    destination: str


# --- Geometría ------------------------------------------------------------------------------


def _distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia por la superficie terrestre (haversine), en millas náuticas."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a)) / NAUTICAL_MILE_KM


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rumbo inicial de un punto a otro, en grados (0 = norte, 90 = este)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def _route(scenario: Scenario) -> tuple[Waypoint, ...]:
    if scenario != "northbound":
        return ROUTE
    # De Pacífico a Atlántico: mismos puntos al revés; cada tramo conserva su velocidad.
    reversed_points = ROUTE[::-1]
    return tuple(
        Waypoint(point.name, point.lat, point.lon, reversed_points[index + 1].speed_kn)
        if index + 1 < len(reversed_points)
        else Waypoint(point.name, point.lat, point.lon, 0.0)
        for index, point in enumerate(reversed_points)
    )


def _transit_fix(route: Sequence[Waypoint], elapsed: timedelta) -> _Fix:
    """Dónde está un buque en tránsito tras `elapsed` desde que dejó el primer fondeadero."""
    remaining_h = elapsed.total_seconds() / 3600
    destination = "BALBOA" if route[-1].lat < route[0].lat else "CRISTOBAL"
    for start, end in itertools.pairwise(route):
        leg_nm = _distance_nm(start.lat, start.lon, end.lat, end.lon)
        leg_h = leg_nm / start.speed_kn
        if remaining_h < leg_h:
            fraction = remaining_h / leg_h
            return _Fix(
                lat=start.lat + (end.lat - start.lat) * fraction,
                lon=start.lon + (end.lon - start.lon) * fraction,
                sog=start.speed_kn,
                cog=_bearing(start.lat, start.lon, end.lat, end.lon),
                nav_status=NAV_UNDERWAY,
                destination=destination,
            )
        remaining_h -= leg_h
    # Llegó: queda fondeado en el destino.
    return _Fix(route[-1].lat, route[-1].lon, 0.0, 0.0, NAV_AT_ANCHOR, destination)


def transit_duration(scenario: Scenario = "southbound") -> timedelta:
    route = _route(scenario)
    hours = sum(
        _distance_nm(a.lat, a.lon, b.lat, b.lon) / a.speed_kn for a, b in itertools.pairwise(route)
    )
    return timedelta(hours=hours)


# --- Mensajes con el formato de AISStream ---------------------------------------------------


def _padded(text: str, size: int = 20) -> str:
    # AIS rellena los textos de 6 bits con '@' hasta su longitud fija.
    return text.upper()[:size].ljust(size, "@")


def _position_payload(
    vessel: SimulatedVessel,
    at: datetime,
    lat: float,
    lon: float,
    sog: float,
    cog: float,
    heading: int,
    nav_status: int,
) -> dict[str, Any]:
    return {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": vessel.mmsi,
            "ShipName": vessel.name,
            "Latitude": lat,
            "Longitude": lon,
        },
        "Message": {
            "PositionReport": {
                "MessageID": 1,
                "RepeatIndicator": 0,
                "UserID": vessel.mmsi,
                "Valid": True,
                "NavigationalStatus": nav_status,
                "RateOfTurn": 0,
                "Sog": sog,
                "PositionAccuracy": True,
                "Longitude": lon,
                "Latitude": lat,
                "Cog": cog,
                "TrueHeading": heading,
                "Timestamp": at.second,
                "SpecialManoeuvreIndicator": 0,
                "Spare": 0,
                "Raim": False,
                "CommunicationState": 0,
            }
        },
    }


def _static_payload(
    vessel: SimulatedVessel, at: datetime, lat: float, lon: float, destination: str
) -> dict[str, Any]:
    eta = at + timedelta(hours=10)
    # Antena a 1/3 de la eslora desde la proa y centrada en la manga.
    to_bow = vessel.length_m // 3
    to_port = vessel.beam_m // 2
    return {
        "MessageType": "ShipStaticData",
        "MetaData": {
            "MMSI": vessel.mmsi,
            "ShipName": vessel.name,
            "Latitude": lat,
            "Longitude": lon,
        },
        "Message": {
            "ShipStaticData": {
                "MessageID": 5,
                "RepeatIndicator": 0,
                "UserID": vessel.mmsi,
                "Valid": True,
                "AisVersion": 2,
                "ImoNumber": vessel.imo,
                "CallSign": _padded(vessel.call_sign, 7),
                "Name": _padded(vessel.name),
                "Type": vessel.ship_type,
                "Dimension": {
                    "A": to_bow,
                    "B": vessel.length_m - to_bow,
                    "C": to_port,
                    "D": vessel.beam_m - to_port,
                },
                "FixType": 1,
                "Eta": {"Month": eta.month, "Day": eta.day, "Hour": eta.hour, "Minute": eta.minute},
                "MaximumStaticDraught": vessel.draught_m,
                "Destination": _padded(destination),
                "Dte": False,
                "Spare": 0,
            }
        },
    }


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


# Variantes inválidas: cada una con el motivo exacto con el que el parser (3.2) la rechaza.
def _invalid_variants(payload: dict[str, Any]) -> list[tuple[str, str]]:
    report = payload["Message"]["PositionReport"]

    def variant(metadata_mmsi: int | None = None, **changes: Any) -> str:
        mutated = json.loads(_dumps(payload))
        mutated["Message"]["PositionReport"].update(changes)
        if metadata_mmsi is not None:
            mutated["MetaData"]["MMSI"] = metadata_mmsi
        return _dumps(mutated)

    return [
        ('{"MessageType": "PositionReport", "MetaData": ', "invalid_json"),
        (variant(metadata_mmsi=12345678, UserID=12345678), "invalid_mmsi"),
        (variant(Latitude=91), "invalid_position"),
        (variant(Latitude=0, Longitude=0), "no_position"),
        (variant(UserID=report["UserID"] + 1), "mmsi_mismatch"),
        (variant(Valid=False), "invalid_message"),
    ]


# --- Generación -----------------------------------------------------------------------------


def _anchored_fix(vessel: SimulatedVessel, rng: random.Random) -> _Fix:
    center = ATLANTIC_ANCHORAGE if vessel.scenario == "anchored_atlantic" else PACIFIC_ANCHORAGE
    # Posición fija por buque (semilla derivada del MMSI): cada uno tiene su sitio.
    spot = random.Random(vessel.mmsi)  # noqa: S311 (simulación, no criptografía)
    lat = center[0] + spot.uniform(-ANCHORAGE_RADIUS_DEG, ANCHORAGE_RADIUS_DEG)
    lon = center[1] + spot.uniform(-ANCHORAGE_RADIUS_DEG, ANCHORAGE_RADIUS_DEG)
    destination = "BALBOA" if vessel.scenario == "anchored_atlantic" else "CRISTOBAL"
    # Fondeado: borneo lento y deriva de pocas décimas de nudo.
    return _Fix(lat, lon, round(rng.uniform(0.0, 0.3), 1), rng.uniform(0, 359.9), 1, destination)


def _fix(vessel: SimulatedVessel, elapsed: timedelta, rng: random.Random) -> _Fix:
    if vessel.scenario in ("anchored_atlantic", "anchored_pacific"):
        return _anchored_fix(vessel, rng)
    scenario: Scenario = "northbound" if vessel.scenario == "northbound" else "southbound"
    return _transit_fix(_route(scenario), elapsed)


def _vessel_messages(
    vessel: SimulatedVessel,
    start: datetime,
    end: datetime,
    rng: random.Random,
    invalid_ratio: float,
) -> Iterator[SimulatedMessage]:
    at = start + timedelta(seconds=rng.uniform(0, 20))  # que no emitan todos a la vez
    next_static = at
    while at < end:
        fix = _fix(vessel, vessel.elapsed_at_start + (at - start), rng)
        silent = vessel.scenario == "signal_loss" and (
            start + SIGNAL_LOSS_WINDOW[0] <= at < start + SIGNAL_LOSS_WINDOW[1]
        )
        lat = round(fix.lat + rng.gauss(0, 0.00002), 6)
        lon = round(fix.lon + rng.gauss(0, 0.00002), 6)
        if not silent and at >= next_static:
            payload = _static_payload(vessel, at, lat, lon, fix.destination)
            yield SimulatedMessage(at, vessel.mmsi, "static", _dumps(payload), lat=lat, lon=lon)
            next_static = at + STATIC_INTERVAL
        if not silent:
            moving = fix.nav_status == NAV_UNDERWAY
            sog = round(max(0.0, fix.sog + rng.gauss(0, 0.2)), 1) if moving else fix.sog
            cog = round((fix.cog + rng.gauss(0, 1.0)) % 360, 1)
            if cog >= 360:
                cog = 0.0
            heading = round(cog + rng.gauss(0, 2.0)) % 360
            payload = _position_payload(vessel, at, lat, lon, sog, cog, heading, fix.nav_status)
            if invalid_ratio and rng.random() < invalid_ratio:
                raw, reason = rng.choice(_invalid_variants(payload))
                yield SimulatedMessage(at, vessel.mmsi, "invalid", raw, expected_reason=reason)
            else:
                yield SimulatedMessage(
                    at, vessel.mmsi, "position", _dumps(payload), lat=lat, lon=lon
                )
        at += UNDERWAY_INTERVAL if fix.nav_status == NAV_UNDERWAY else ANCHORED_INTERVAL


def generate(
    *,
    start: datetime,
    duration: timedelta,
    seed: int = 0,
    fleet: Sequence[SimulatedVessel] = DEFAULT_FLEET,
    invalid_ratio: float = 0.0,
) -> list[SimulatedMessage]:
    """Todos los mensajes de la flota entre `start` y `start + duration`, ordenados por hora."""
    if start.tzinfo is None:
        raise ValueError("start debe llevar zona horaria (UTC)")
    if not timedelta(0) < duration <= timedelta(minutes=MAX_MINUTES):
        raise ValueError(f"La duración debe estar entre 1 y {MAX_MINUTES} minutos")
    if not 0 <= invalid_ratio <= 1:
        raise ValueError("invalid_ratio debe estar entre 0 y 1")
    end = start + duration
    messages: list[SimulatedMessage] = []
    for index, vessel in enumerate(fleet):
        rng = random.Random(f"{seed}:{index}:{vessel.mmsi}")  # noqa: S311 (simulación)
        messages.extend(_vessel_messages(vessel, start, end, rng, invalid_ratio))
    return sorted(messages, key=lambda message: (message.at, message.mmsi, message.kind))


# --- Servidor WebSocket que imita a AISStream -----------------------------------------------


@dataclass(frozen=True, slots=True)
class Subscription:
    # Cajas como (lat_min, lon_min, lat_max, lon_max).
    boxes: tuple[tuple[float, float, float, float], ...]
    message_types: frozenset[str] | None = None
    mmsi: frozenset[int] | None = None

    def accepts(self, message: SimulatedMessage) -> bool:
        if message.kind == "invalid":
            return True  # los inválidos llegan siempre: sirven para probar al cliente
        if self.message_types is not None and message.message_type not in self.message_types:
            return False
        if self.mmsi is not None and message.mmsi not in self.mmsi:
            return False
        if message.lat is None or message.lon is None:
            return False
        return any(
            lat_min <= message.lat <= lat_max and lon_min <= message.lon <= lon_max
            for lat_min, lon_min, lat_max, lon_max in self.boxes
        )


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_subscription(raw: str | bytes) -> Subscription | None:
    """Valida la suscripción como AISStream; `None` si no es válida (no hay confirmación)."""
    if len(raw) > MAX_SUBSCRIPTION_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    api_key = data.get("APIKey")
    if not isinstance(api_key, str) or not api_key.strip():
        return None

    raw_boxes = data.get("BoundingBoxes")
    if not isinstance(raw_boxes, list) or not raw_boxes:
        return None
    boxes = []
    for box in raw_boxes:
        if not (isinstance(box, list) and len(box) == 2):
            return None
        corners = []
        for corner in box:
            if not (isinstance(corner, list) and len(corner) == 2 and all(map(_number, corner))):
                return None
            lat, lon = corner
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return None
            corners.append((float(lat), float(lon)))
        (lat1, lon1), (lat2, lon2) = corners
        boxes.append((min(lat1, lat2), min(lon1, lon2), max(lat1, lat2), max(lon1, lon2)))

    message_types = data.get("FilterMessageTypes")
    if message_types is not None and not (
        isinstance(message_types, list) and all(isinstance(t, str) for t in message_types)
    ):
        return None

    mmsi_filter = data.get("FiltersShipMMSI")
    if mmsi_filter is not None and not (
        isinstance(mmsi_filter, list)
        and len(mmsi_filter) <= MAX_FILTERED_MMSI
        and all(isinstance(m, str) and len(m) == 9 and m.isdigit() for m in mmsi_filter)
    ):
        return None

    return Subscription(
        boxes=tuple(boxes),
        message_types=frozenset(message_types) if message_types is not None else None,
        mmsi=frozenset(int(m) for m in mmsi_filter) if mmsi_filter is not None else None,
    )


@dataclass
class _Stream:
    messages: Sequence[SimulatedMessage]
    speed: float
    subscription_timeout: float
    sent: list[int] = field(default_factory=list)

    async def handle(self, connection: ServerConnection) -> None:
        try:
            raw = await asyncio.wait_for(connection.recv(), self.subscription_timeout)
        except TimeoutError:
            await connection.close(1008, "subscription timeout")
            return
        except ConnectionClosed:
            return
        subscription = parse_subscription(raw)
        if subscription is None:
            # Igual que AISStream: una suscripción inválida no recibe confirmación.
            await connection.close(1008, "invalid subscription")
            return
        confirmation = {
            "MessageType": "SubscriptionConfirmation",
            "Message": {"CompressionEnabled": bool(connection.protocol.extensions)},
        }
        try:
            await connection.send(_dumps(confirmation).encode())
            await self._replay(connection, subscription)
        except ConnectionClosed:
            return
        await connection.close()

    async def _replay(self, connection: ServerConnection, subscription: Subscription) -> None:
        previous: datetime | None = None
        for message in self.messages:
            if previous is not None and self.speed > 0:
                await asyncio.sleep((message.at - previous).total_seconds() / self.speed)
            previous = message.at
            if subscription.accepts(message):
                # AISStream envía frames binarios con JSON en UTF-8.
                await connection.send(message.raw.encode())
                self.sent.append(message.mmsi)


async def start_server(
    messages: Sequence[SimulatedMessage],
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    speed: float = 60.0,
    subscription_timeout: float = SUBSCRIPTION_TIMEOUT_SECONDS,
) -> Server:
    """Arranca el servidor. `speed=60` reproduce una hora de tráfico en un minuto; 0, sin pausa."""
    if not 0 <= speed <= MAX_SPEED:
        raise ValueError(f"speed debe estar entre 0 y {MAX_SPEED}")
    stream = _Stream(messages, speed, subscription_timeout)
    return await serve(stream.handle, host, port, compression="deflate")


# --- CLI ------------------------------------------------------------------------------------


def _write_jsonl(messages: Iterable[SimulatedMessage]) -> None:
    for message in messages:
        sys.stdout.write(message.raw + "\n")


async def _serve_forever(
    messages: Sequence[SimulatedMessage], host: str, port: int, speed: float
) -> None:
    server = await start_server(messages, host=host, port=port, speed=speed)
    sys.stderr.write(f"Simulador AIS en ws://{host}:{port} ({len(messages)} mensajes)\n")
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulador de tráfico AIS del Canal de Panamá.")
    parser.add_argument("mode", choices=["jsonl", "serve"])
    parser.add_argument("--minutes", type=int, default=60, help=f"duración, de 1 a {MAX_MINUTES}")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--invalid-ratio", type=float, default=0.0, help="de 0 a 1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--speed", type=float, default=60.0, help=f"de 0 a {MAX_SPEED} (0 = sin pausa)"
    )
    args = parser.parse_args(argv)

    try:
        messages = generate(
            start=datetime.now(UTC),
            duration=timedelta(minutes=args.minutes),
            seed=args.seed,
            invalid_ratio=args.invalid_ratio,
        )
        if args.mode == "jsonl":
            _write_jsonl(messages)
        else:
            asyncio.run(_serve_forever(messages, args.host, args.port, args.speed))
    except ValueError as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
