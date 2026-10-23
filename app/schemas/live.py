"""Mensajes de `/ws/live` (docs/API_DESIGN.md, "WebSocket `/ws/live`").

El worker publica `LiveUpdate` en Redis (3.5) y la API lo reenvía a los navegadores (4.2): los dos
usan estos mismos modelos. Los mensajes del cliente se validan como cualquier entrada externa:
tipos estrictos, campos desconocidos rechazados y límites de tamaño (AGENTS.md §8.6).
"""

from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    model_validator,
)

# Buques por mensaje: mantiene cada PUBLISH y cada frame muy por debajo de límites razonables.
MAX_VESSELS_PER_MESSAGE = 200
# Un access token JWT ocupa unos cientos de bytes; más que esto no es un token nuestro.
MAX_TOKEN_LENGTH = 2048

Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]


class LiveVessel(BaseModel):
    """Una posición tal como la recibe el navegador."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mmsi: int = Field(ge=100_000_000, le=999_999_999)
    lon: Longitude
    lat: Latitude
    cog: float | None = Field(ge=0, lt=360)
    sog: float | None = Field(ge=0, lt=102.3)
    ship_type: int | None = Field(ge=1, le=99)
    # Texto del buque tal cual (puede traer "<img ...>"): el navegador lo muestra como texto.
    name: str | None = Field(max_length=128)
    ts: AwareDatetime


class LiveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["update"] = "update"
    vessels: list[LiveVessel] = Field(max_length=MAX_VESSELS_PER_MESSAGE)


class LiveSnapshot(BaseModel):
    """Estado inicial del viewport: el cliente sustituye lo que tuviera por esto."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["snapshot"] = "snapshot"
    vessels: list[LiveVessel]


class LiveRemove(BaseModel):
    """Buques que han salido del viewport: el cliente deja de pintarlos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["remove"] = "remove"
    mmsi: list[int]


# --- Mensajes del cliente -------------------------------------------------------------------


class AuthMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["auth"]
    token: StrictStr = Field(min_length=1, max_length=MAX_TOKEN_LENGTH)

    def __repr__(self) -> str:
        return "AuthMessage(token=<oculto>)"  # nunca el token en un log o un traceback

    __str__ = __repr__


class BBox(BaseModel):
    """Viewport `[min_lon, min_lat, max_lon, max_lat]`, en el orden de GeoJSON."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_lon: Longitude
    min_lat: Latitude
    max_lon: Longitude
    max_lat: Latitude

    @model_validator(mode="after")
    def ordered(self) -> "BBox":
        # Sin cruzar el antimeridiano: el Canal está muy lejos de él.
        if self.min_lon >= self.max_lon or self.min_lat >= self.max_lat:
            raise ValueError("bbox debe ser [min_lon, min_lat, max_lon, max_lat] con min < max")
        return self

    def contains(self, lon: float, lat: float) -> bool:
        return self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat


class SubscribeMessage(BaseModel):
    # strict: "-80.2" (texto) no se convierte en número.
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: Literal["subscribe"]
    bbox: tuple[Longitude, Latitude, Longitude, Latitude]

    def viewport(self) -> BBox:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        return BBox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)

    @model_validator(mode="after")
    def valid_bbox(self) -> "SubscribeMessage":
        self.viewport()  # lanza si el orden no es válido
        return self


ClientMessage = Annotated[AuthMessage | SubscribeMessage, Field(discriminator="type")]
client_message_adapter: TypeAdapter[AuthMessage | SubscribeMessage] = TypeAdapter(ClientMessage)
