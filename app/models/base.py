"""Metadatos ORM compartidos por los modelos de la aplicación."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base declarativa para los modelos persistentes."""
