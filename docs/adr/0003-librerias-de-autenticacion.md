# ADR-0003: PyJWT y pwdlib (Argon2id) para autenticación

- **Fecha**: 2026-10-15
- **Estado**: Aceptada. Comprobada con la instalación real: PyJWT y pwdlib con Argon2id están en uso

## Contexto
El scaffold inicial usaba `python-jose` y `passlib[bcrypt]`. Ambas librerías tienen muy poca
actividad de mantenimiento, y `passlib` 1.7.4 tiene incompatibilidades conocidas con versiones
recientes de `bcrypt` (≥ 4.1), lo que puede romper el hashing de forma inesperada al instalar
dependencias nuevas.

## Decisión
- **PyJWT** para emitir y validar tokens.
- **pwdlib** con **Argon2id** para hashing de contraseñas (ganador de la Password Hashing
  Competition y recomendación actual de OWASP para almacenamiento de contraseñas).
- Refresh tokens con `jti` persistido en la tabla `refresh_tokens`, con rotación y revocación.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| python-jose + passlib | mantenimiento bajo, incompatibilidades con bcrypt reciente |
| bcrypt directo | válido, pero Argon2id es la opción recomendada hoy y pwdlib permite migrar hashes |
| Proveedor externo (Auth0, Clerk) | oculta justo lo que el proyecto quiere demostrar |

## Consecuencias
- `docs/ENGINEERING.md` y el código usan Argon2id; ninguna referencia a bcrypt/passlib.
- Antes de la Fase 2: verificar que las versiones de `pyproject.toml` instalan y pasan tests.
