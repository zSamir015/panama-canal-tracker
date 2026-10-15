# CLAUDE.md

Las instrucciones del proyecto viven en `AGENTS.md`, que es la fuente única de verdad para todos los
asistentes. Claude Code lo importa aquí:

@AGENTS.md

## Notas específicas para Claude Code

- Antes de cada tarea, leer el issue correspondiente y la fase actual en `docs/ROADMAP.md`.
- Planificar antes de editar en tareas de más de un archivo; proponer el plan si la tarea toca
  arquitectura o un ADR.
- Ejecutar `pytest`, `ruff check .` y `mypy app` antes de dar una tarea por terminada.
- No añadir trailers `Co-Authored-By` ni líneas "Generated with Claude Code" en commits ni PRs
  (AGENTS.md §2.9).
- Aplicar la sección 8 de AGENTS.md (seguridad) en cada cambio y marcar el checklist de seguridad
  de la plantilla de PR. Si una regla de seguridad no se puede cumplir, detenerse y explicarlo.
