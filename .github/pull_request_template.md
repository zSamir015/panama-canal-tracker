## Qué cambia

<!-- Antes / después, en lenguaje simple. -->

## Issue

Closes #

## Fase del roadmap

<!-- Ej.: Fase 1 — tarea 1.2 -->

## Cómo se probó

- [ ] `pytest` verde
- [ ] `ruff check .` y `ruff format --check .` limpios
- [ ] `mypy app` sin errores
- [ ] Probado manualmente (describir):

## Checklist de seguridad (AGENTS.md §8)

- [ ] No hay secretos, `.env`, datos personales ni rutas locales en el diff, capturas o GIFs
- [ ] Endpoints nuevos: requieren auth (o están en la lista blanca justificada) y tienen tests 401/403
- [ ] Recursos de usuario filtrados por el `user_id` del token (test de acceso cruzado → 404)
- [ ] Entradas validadas con Pydantic (`extra="forbid"`, límites); SQL solo parametrizado
- [ ] Datos externos (AIS, usuario) nunca se renderizan como HTML
- [ ] Dependencias nuevas: usadas por el código, lockfiles regenerados, `pip-audit` limpio
- [ ] Sin `debug`, `print` ni logs con tokens o contraseñas

## Checklist general

- [ ] Si se tomó una decisión de arquitectura, hay un ADR nuevo en `docs/adr/`
- [ ] Docs actualizados si cambió un contrato (API, modelo de datos)
