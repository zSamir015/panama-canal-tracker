# Copilot Instructions — Panama Canal Tracker

La fuente única de verdad es **`AGENTS.md`** en la raíz del repositorio. Léelo antes de sugerir
código. Resumen de lo esencial:

- Proyecto por fases: no sugerir código de fases futuras (ver `docs/ROADMAP.md`).
- Backend: Python 3.12, todo `async`, type hints completos, SQLAlchemy 2.0 async, Pydantic v2.
- Capas: `routers/` → `services/` → `repositories/` → `models/`. Nada de lógica en routers ni
  modelos ORM en responses. Schemas con sufijos `Create` / `Update` / `Response`.
- Dependencias: `get_db`, `get_current_user`, `require_admin` vía `Depends`.
- Errores de dominio en `services/`, traducidos a `application/problem+json` (RFC 9457) por un
  handler global. Mensajes en español.
- Auth: PyJWT + pwdlib (Argon2id). Secrets solo desde `app/core/config.py`. Jamás literales.
- AISStream: una sola conexión, solo en el proceso worker (`app/workers/`), con backoff.
- Frontend (`web/`): React + TypeScript strict + MapLibre GL; buques como capa GeoJSON.
- Tests: pytest + httpx.AsyncClient; cubrir 401/403/404/422. Nada depende de AISStream real.
- Estilo: ruff, líneas ≤ 100. Identificadores en inglés; docstrings de negocio en español.
- Conventional Commits en inglés. **Sin créditos a asistentes de IA** en commits, PRs ni código.
- **Seguridad (AGENTS.md §8, obligatoria)**: denegar por defecto (todo endpoint con auth salvo
  lista blanca); admin solo vía router con `require_admin`; recursos propios filtrados por el
  `user_id` del token (404 si no es suyo); Pydantic con `extra="forbid"` y límites; SQL solo
  parametrizado; nada de `dangerouslySetInnerHTML` ni `setHTML` (los nombres AIS no son
  confiables); CORS con orígenes explícitos; cabeceras de seguridad; sin `debug=True`;
  secretos como `SecretStr` y nunca en logs; refresh token en cookie HttpOnly.
- Documentación nivel senior en cada PR (diagramas Mermaid, capturas/GIFs en `docs/media/`),
  **sin exponer** API keys, tokens, `.env`, datos personales ni rutas locales (AGENTS.md §7.1).
