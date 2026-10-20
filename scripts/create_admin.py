"""Crea un usuario administrador (AGENTS.md §8.3).

La API nunca crea admins: el registro siempre asigna el rol `user`. El primer admin se crea con
este script, con acceso a la base (`DATABASE_URL` de `.env`):

    python scripts/create_admin.py admin@example.com

La contraseña se pide por teclado dos veces y no se muestra; nunca va como argumento, porque los
argumentos quedan en el historial de la shell y en la lista de procesos.
"""

import argparse
import asyncio
import getpass
import sys
from uuid import UUID

import structlog
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionFactory, create_engine, create_session_factory
from app.core.logging import configure_logging
from app.core.security import PasswordPolicyError, check_password_policy, hash_password
from app.models.user import UserRole
from app.repositories.user import UserRepository, normalize_email

DUPLICATE_EMAIL = "Ya existe un usuario con ese email"

email_adapter: TypeAdapter[str] = TypeAdapter(EmailStr)


class AdminCreationError(Exception):
    """Datos inválidos o email ya registrado. El mensaje se puede mostrar al operador."""


def validate_email(email: str) -> str:
    try:
        return normalize_email(email_adapter.validate_python(email))
    except ValidationError:
        raise AdminCreationError("El email no es válido") from None


async def create_admin(session_factory: SessionFactory, email: str, password: str) -> UUID:
    """Valida los datos, crea el admin y confirma la transacción. Devuelve su id."""
    email = validate_email(email)
    try:
        check_password_policy(password)
    except PasswordPolicyError as error:
        raise AdminCreationError(str(error)) from None

    async with session_factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(email) is not None:
            raise AdminCreationError(DUPLICATE_EMAIL)
        try:
            user = await users.add(
                email=email, hashed_password=hash_password(password), role=UserRole.ADMIN
            )
            await session.commit()
        except IntegrityError:
            # Otro proceso registró el mismo email entre la consulta y el INSERT.
            raise AdminCreationError(DUPLICATE_EMAIL) from None
        return user.id


def read_password() -> str:
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repite la contraseña: "):
        raise AdminCreationError("Las contraseñas no coinciden")
    return password


async def run(email: str, password: str) -> UUID:
    engine = create_engine(get_settings())
    try:
        return await create_admin(create_session_factory(engine), email, password)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea un usuario administrador.")
    parser.add_argument("email")
    args = parser.parse_args(argv)

    configure_logging(get_settings().log_level)
    logger = structlog.get_logger("create_admin")
    try:
        email = validate_email(args.email)
        user_id = asyncio.run(run(email, read_password()))
    except AdminCreationError as error:
        logger.error("admin_not_created", reason=str(error))
        return 1
    # Auditoría: quién se creó y cuándo (el timestamp lo pone el log). Sin email ni contraseña.
    logger.info("admin_created", user_id=str(user_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
