"""Estado de la ingesta AIS: lo escribe el worker en Redis (3.5) y lo devuelve la API (3.9)."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WorkerStatus(BaseModel):
    """Contadores del worker AIS en un momento dado (`canal:ais:worker:status`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    updated_at: AwareDatetime
    connected: bool
    subscribed: bool
    connections: int
    last_message_at: AwareDatetime | None
    last_error: str | None
    received: int
    queued: int
    queue_size: int
    dropped: int
    ignored: int
    rejected: dict[str, int]
    batches: int
    positions_written: int
    positions_duplicated: int
    rows_rejected_by_db: int
    batches_dropped: int
    last_flush_at: AwareDatetime | None


class IngestionStatusResponse(BaseModel):
    """`GET /admin/ingestion/status`. Sin estado en Redis (`available=false`): el worker está
    parado o no actualiza desde hace más de la caducidad de la clave."""

    available: bool
    # El worker actualiza cada 5 s; si el estado tiene más de 30 s, algo va mal aunque exista.
    stale: bool = False
    age_seconds: float | None = Field(default=None, ge=0)
    status: WorkerStatus | None = None
