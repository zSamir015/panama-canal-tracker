# ADR-0017: `v1.0.0` sin entorno de producción

- **Fecha**: 2026-11-19
- **Estado**: Aceptada

## Contexto
La Fase 7 se llama "Producción y pulido de portafolio", y dos de sus tareas dan por hecho que hay
un servidor: la 7.2 (copias automáticas de la base) y la 7.6 (revisión de seguridad final, que
según `docs/SECURITY_REVIEW.md` exige configurar el proxy con HSTS, redirección a HTTPS, límites
por IP, bloqueo de `/metrics` y `frame-ancestors`, y repetir la revisión contra él).

Ese servidor no existe ni está previsto. ADR-0011 sustituyó el VPS por una demo estática en
GitHub Pages por coste y mantenimiento, ADR-0012 llevó la recolección de AIS a GitHub Actions, y
la validación de la 5.7 (`docs/VALIDATION.md`) descartó gastar para mejorar la cobertura. Sin una
decisión, la 7.2 y la 7.6 no se pueden cerrar nunca y `v1.0.0` queda bloqueado.

## Decisión
`v1.0.0` se entrega **sin entorno de producción**. El alcance es:

1. La **demo estática** en GitHub Pages (ADR-0011), que es lo que está publicado.
2. La **pila completa local** con `docker compose` (API, worker, base de datos y Redis), que es
   lo que se ejecuta con datos reales.

Con ese alcance:

- **7.2 se cierra** cuando las copias están listas para programarse sin tocar los scripts:
  cifradas, con restauración probada de punta a punta y con la retención dentro de
  `scripts/db_backup.sh` (`BACKUP_KEEP_DAYS`), probada en `scripts/db_backup_check.sh`. La
  programación (cron o un temporizador de systemd) se documenta en `docs/BACKUP.md` y se instala
  en el servidor el día que exista.
- **7.6 se cierra** con la revisión de lo que sí existe: la demo de Pages, la pila local, las
  dependencias, el historial, las capturas y el código de autenticación, CORS y administración
  leído línea a línea. Lo que solo tiene sentido en un servidor (proxy, HSTS, redirección,
  límites por IP, bloqueo de `/metrics`, `frame-ancestors`) se deja escrito como **requisito
  previo a cualquier despliegue**, no como hecho.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| VPS de pago con compose, proxy y TLS | Coste mensual y mantenimiento que ADR-0011 ya rechazó para un proyecto de portafolio |
| Free tier (Oracle Cloud Always Free) | Exige tarjeta, la cuenta puede reclamar instancias inactivas y sigue siendo un servidor que mantener |
| Dejar la 7.2 y la 7.6 abiertas | `v1.0.0` no llegaría nunca, y el roadmap diría que falta algo que se decidió no hacer |

## Consecuencias
- El README y `docs/SECURITY_REVIEW.md` deben decir con claridad que no hay despliegue y qué
  faltaría para tenerlo: nadie debe leer `v1.0.0` como "en producción".
- Las copias nunca se han programado ni restaurado en un servidor real; `docs/BACKUP.md` lo deja
  en "Límites".
- Si en el futuro se despliega, ese trabajo (proxy, cabeceras, copias programadas y fuera de la
  máquina, revisión contra el entorno vivo) es una tarea nueva con su propio ADR, y esta decisión
  pasa a "Sustituida".
