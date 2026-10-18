"""Metadatos ORM compartidos por los modelos de la aplicación."""

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import SchemaItem

# Tablas que crean las extensiones (PostGIS) en `public`. No son nuestras: Alembic no debe
# proponer borrarlas al comparar la base con los modelos.
EXTENSION_TABLES = frozenset({"spatial_ref_sys"})


class Base(DeclarativeBase):
    """Base declarativa para los modelos persistentes."""


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Filtro `include_object` de Alembic: ignora las tablas de las extensiones."""
    return not (type_ == "table" and reflected and compare_to is None and name in EXTENSION_TABLES)
