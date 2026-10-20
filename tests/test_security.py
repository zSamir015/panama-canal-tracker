import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core import security
from app.core.config import Settings
from app.core.security import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    REQUIRED_CLAIMS,
    InvalidAccessTokenError,
    PasswordPolicyError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

PASSWORD = "caballo-bateria-grapa"


@pytest.fixture
def settings(app_settings: Settings) -> Settings:
    return app_settings


def claims(settings: Settings, **overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": uuid4().hex,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def sign(payload: dict[str, Any], settings: Settings, **kwargs: Any) -> str:
    return jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), **kwargs)


# --- Contraseñas ---------------------------------------------------------------------------


def test_hash_is_argon2id_and_never_the_plain_password() -> None:
    hashed = hash_password(PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed
    assert hash_password(PASSWORD) != hashed  # sal aleatoria en cada hash


def test_verify_accepts_the_right_password_only() -> None:
    hashed = hash_password(PASSWORD)

    assert verify_password(PASSWORD, hashed) == (True, None)
    assert verify_password(PASSWORD + "x", hashed) == (False, None)


@pytest.mark.parametrize(
    "length", [PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH], ids=["minimo", "maximo"]
)
def test_policy_accepts_the_length_limits(length: int) -> None:
    assert verify_password("a" * length, hash_password("a" * length)).valid


@pytest.mark.parametrize(
    "password",
    ["", "a" * (PASSWORD_MIN_LENGTH - 1), "a" * (PASSWORD_MAX_LENGTH + 1)],
    ids=["vacia", "corta", "larga"],
)
def test_policy_rejects_lengths_outside_the_limits(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="entre 12 y 128"):
        hash_password(password)


def test_policy_has_no_composition_rules() -> None:
    # NIST SP 800-63B: ni mayúsculas ni números ni símbolos obligatorios.
    hash_password("todo en minusculas y sin numeros")


def test_policy_counts_characters_not_bytes() -> None:
    # 12 caracteres, 24 bytes en UTF-8.
    hash_password("ñ" * PASSWORD_MIN_LENGTH)
    with pytest.raises(PasswordPolicyError):
        hash_password("ñ" * (PASSWORD_MIN_LENGTH - 1))


def test_verify_rejects_overlong_passwords_without_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: object) -> None:
        raise AssertionError("no debe hashear")

    monkeypatch.setattr(security.password_hash, "verify", fail)
    monkeypatch.setattr(security.password_hash, "verify_and_update", fail)

    assert verify_password("a" * (PASSWORD_MAX_LENGTH + 1), None) == (False, None)


def test_unknown_user_still_runs_a_real_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_verify = security.password_hash.verify

    def spy(password: str, hashed: str) -> bool:
        calls.append(hashed)
        return real_verify(password, hashed)

    monkeypatch.setattr(security.password_hash, "verify", spy)

    assert verify_password(PASSWORD, None) == (False, None)
    [dummy] = calls
    assert dummy.startswith("$argon2id$")


def test_unknown_user_takes_as_long_as_a_wrong_password() -> None:
    # Anti-enumeración: sin el hash ficticio, un email inexistente respondería en microsegundos.
    hashed = hash_password(PASSWORD)
    verify_password(PASSWORD, None)  # calcula el hash ficticio fuera de la medición

    def elapsed(stored: str | None) -> float:
        start = time.perf_counter()
        verify_password("otra-contraseña-cualquiera", stored)
        return time.perf_counter() - start

    unknown = min(elapsed(None) for _ in range(3))
    wrong = min(elapsed(hashed) for _ in range(3))
    assert unknown > wrong / 3


def test_hash_with_old_parameters_is_upgraded() -> None:
    old = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8192, parallelism=1),))
    old_hash = old.hash(PASSWORD)

    valid, new_hash = verify_password(PASSWORD, old_hash)

    assert valid
    assert new_hash is not None and new_hash != old_hash
    assert verify_password(PASSWORD, new_hash) == (True, None)


def test_wrong_password_never_returns_a_new_hash() -> None:
    old = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8192, parallelism=1),))

    assert verify_password("otra-contraseña", old.hash(PASSWORD)) == (False, None)


# --- Access tokens -------------------------------------------------------------------------


def test_token_roundtrip_carries_the_user_and_all_required_claims(settings: Settings) -> None:
    user_id = uuid4()
    now = datetime.now(UTC).replace(microsecond=0)

    token, issued = create_access_token(user_id, settings, now=now)
    decoded = decode_access_token(token, settings)

    assert decoded == issued
    assert decoded.user_id == user_id
    assert decoded.expires_at == now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert set(payload) == set(REQUIRED_CLAIMS)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"


def test_each_token_gets_a_unique_jti(settings: Settings) -> None:
    user_id = uuid4()

    _, first = create_access_token(user_id, settings)
    _, second = create_access_token(user_id, settings)

    assert first.jti != second.jti


def test_token_does_not_carry_the_role(settings: Settings) -> None:
    token, _ = create_access_token(uuid4(), settings)

    payload = jwt.decode(token, options={"verify_signature": False})
    assert "role" not in payload  # el rol se lee de la base en cada petición


def test_expired_token_is_rejected(settings: Settings) -> None:
    past = datetime.now(UTC) - timedelta(minutes=settings.access_token_expire_minutes + 1)
    token, _ = create_access_token(uuid4(), settings, now=past)

    with pytest.raises(InvalidAccessTokenError, match="ExpiredSignatureError"):
        decode_access_token(token, settings)


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    forged = jwt.encode(claims(settings), "otra-clave-de-32-bytes-como-minimo!!", algorithm="HS256")

    with pytest.raises(InvalidAccessTokenError, match="InvalidSignatureError"):
        decode_access_token(forged, settings)


def test_tampered_payload_is_rejected(settings: Settings) -> None:
    token, _ = create_access_token(uuid4(), settings)
    header, _, signature = token.split(".")
    other_payload = sign(claims(settings), settings, algorithm="HS256").split(".")[1]

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(f"{header}.{other_payload}.{signature}", settings)


def test_alg_none_is_rejected(settings: Settings) -> None:
    unsigned = jwt.encode(claims(settings), key=None, algorithm="none")

    with pytest.raises(InvalidAccessTokenError, match="InvalidAlgorithmError"):
        decode_access_token(unsigned, settings)

    # HS512 no está en la lista aceptada. Clave de 64 bytes: el mínimo que PyJWT pide para HS512.


def test_other_hmac_algorithm_is_rejected(settings: Settings) -> None:
    # Firmado con la misma clave, pero HS512 no está en la lista; clave de 64 bytes para HS512.
    token = jwt.encode(claims(settings), "k" * 64, algorithm="HS512")

    with pytest.raises(InvalidAccessTokenError, match="InvalidAlgorithmError"):
        decode_access_token(token, settings)


@pytest.mark.parametrize(
    ("claim", "value", "error"),
    [
        ("aud", "otra-api", "InvalidAudienceError"),
        ("iss", "otro-emisor", "InvalidIssuerError"),
        ("sub", "no-es-un-uuid", "ValueError"),
        ("sub", 42, "InvalidSubjectError"),
        ("iat", datetime.now(UTC) + timedelta(hours=1), "ImmatureSignatureError"),
    ],
)
def test_wrong_claim_is_rejected(settings: Settings, claim: str, value: object, error: str) -> None:
    token = sign(claims(settings, **{claim: value}), settings, algorithm="HS256")

    with pytest.raises(InvalidAccessTokenError, match=error):
        decode_access_token(token, settings)


@pytest.mark.parametrize("claim", REQUIRED_CLAIMS)
def test_token_missing_a_required_claim_is_rejected(settings: Settings, claim: str) -> None:
    payload = claims(settings)
    del payload[claim]
    token = sign(payload, settings, algorithm="HS256")

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
def test_malformed_token_is_rejected(settings: Settings, garbage: str) -> None:
    with pytest.raises(InvalidAccessTokenError, match="DecodeError"):
        decode_access_token(garbage, settings)


def test_error_message_never_contains_the_token(settings: Settings) -> None:
    token = sign(claims(settings, aud="otra-api"), settings, algorithm="HS256")

    with pytest.raises(InvalidAccessTokenError) as caught:
        decode_access_token(token, settings)

    assert token not in str(caught.value)
    assert caught.value.__cause__ is None


def test_settings_only_allow_hs256() -> None:
    with pytest.raises(ValueError, match="HS256"):
        Settings(_env_file=None, jwt_algorithm="none")  # type: ignore[arg-type]


def test_settings_bound_the_access_token_lifetime() -> None:
    with pytest.raises(ValueError, match="access_token_expire_minutes"):
        Settings(_env_file=None, access_token_expire_minutes=0)
    with pytest.raises(ValueError, match="access_token_expire_minutes"):
        Settings(_env_file=None, access_token_expire_minutes=24 * 60)
