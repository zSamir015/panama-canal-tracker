# ADR-0019: Recolector AIS continuo y ejecución simultánea con worker local

- **Fecha**: 2026-11-20
- **Estado**: Aceptada
- **Modifica**: [ADR-0009](0009-segunda-conexion-destinos-al-canal.md), [ADR-0012](0012-recolector-ais-en-github-actions.md) y la regla 6 de `AGENTS.md`

## Contexto
La validación con 12,5 días de datos reales (`docs/VALIDATION.md`) mostró dos límites operativos:

1. **Huecos del recolector por cron**: GitHub Actions retrasa u omite ejecuciones programadas cada 6
   horas; en la práctica solo se escuchó el **52,2 %** del tiempo (`156,3 h` de `299,4 h`).
2. **Simultaneidad con worker local**: AISStream permite un máximo de 3 conexiones simultáneas por
   API key. Hasta ahora el worker abría dos (`canal_area` + `canal_bound`, ADR-0009) y el recolector
   una, por lo que no se ejecutaban a la vez; además, la segunda conexión `canal_bound` aportó muy
   pocos buques útiles en prueba frente al valor de tener tanto el worker local como el recolector
   de GitHub corriendo de forma estable.

## Decisión
1. **Encadenamiento continuo del recolector (`.github/workflows/collect-ais.yml`)**:
   - Un job separado `chain` (`needs: collect`, `timeout-minutes: 5`, sin secretos ni acciones de
     terceros, con `permissions: actions: write`) comprueba que no exista ninguna ejecución pendiente
     y dispara la siguiente ventana con `gh workflow run collect-ais.yml --ref main -f minutes=340 -f chain=true`.
   - Solo se ejecuta si `needs.collect.result == 'success'`, `AIS_COLLECT_ENABLED == 'true'`,
     `github.ref == 'refs/heads/main'` y (`schedule` o `inputs.chain == true`).
   - El `cron: "23 */6 * * *"` se mantiene únicamente como respaldo si la cadena se interrumpe.
2. **Convivencia worker + recolector mediante `AIS_CANAL_BOUND_ENABLED=false`**:
   - Cuando el worker local (por ejemplo en macOS con `launchd` + `caffeinate -i -s`) corre a la
     vez que `collect-ais.yml` usando la misma `AISSTREAM_API_KEY`, el worker se arranca con
     `AIS_CANAL_BOUND_ENABLED=false` (1 conexión). Así `1` conexión del worker + `1` conexión del
     recolector suman **2 conexiones**, dentro del presupuesto máximo de la regla 6 de `AGENTS.md`.
   - La segunda conexión (`canal_bound`) queda desactivada en este modo hasta contar con un VPS
     permanente y retirar el recolector de Actions.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Seguir solo con `cron` cada 6 h en Actions | Pierde casi la mitad del tiempo de escucha por colas y omisiones |
| Dar `actions: write` al mismo job `collect` y encadenar con `always()` | Expone permisos de escritura al job con secretos y crea bucles infinitos si falla la API key |
| Mantener `AIS_CANAL_BOUND_ENABLED=true` con recolector activo | Alcanzaría 3 conexiones (en el límite duro de AISStream) sin espacio para reconexiones |

## Consecuencias
- La cobertura temporal del recolector sube de ~52 % a ~95 % con pausas breves entre ventanas.
- **Zona gris en las condiciones de GitHub (riesgo heredado de ADR-0012, ampliado)**: con el
  encadenamiento, Actions trabaja casi 24/7, acercándose más al uso como servidor permanente que
  las condiciones de servicio restringen. Si GitHub limitara Actions en el repositorio, se apaga
  al instante cambiando `AIS_COLLECT_ENABLED` a `false`.
- Al aislar `actions: write` en `chain` (solo en `main` y solo tras `success`), ningún fallo de
  secretos o de red genera bucles de disparo.
- `docs/AIS_COLLECTOR.md`, `docs/LOCAL_WORKER_MAC.md`, ADR-0012 y la regla 6 de `AGENTS.md` pasan a
  reflejar la regla explícita: **a la vez solo con `AIS_CANAL_BOUND_ENABLED=false`**.
