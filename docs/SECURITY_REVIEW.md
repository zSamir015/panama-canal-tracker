# Revisión de seguridad (tarea 7.6)

Revisión de lo construido contra `AGENTS.md` §8, hecha el 2026-11-06 sobre las ramas de las
tareas 5.3 a 7.3. **Es una revisión parcial**: dice qué se comprobó hoy ejecutando algo, qué se
da por bueno porque un test existente pasa, y qué sigue pendiente. La casilla 7.6 del roadmap no
se marca: hay hallazgos abiertos (más abajo), el principal es que no existe todavía el entorno de
producción.

## Cómo se comprobó

| Comprobación (ejecutada hoy) | Resultado |
|---|---|
| `gitleaks detect` sobre los 100 commits del historial | Sin hallazgos |
| `pip-audit --strict` con los dos lockfiles | Sin vulnerabilidades conocidas |
| `npm audit` en `web/` | 0 vulnerabilidades |
| Autores de los commits | 99 con el `noreply` del dueño y 2 de Dependabot; ningún correo personal |
| `debug=True`, `print(`, `os.environ` fuera de `app/core/config.py` | Ninguno |
| `dangerouslySetInnerHTML`, `innerHTML`, `setHTML`, `eval(` en `web/src` | Ninguno fuera de los tests y de la regla de ESLint |
| `text(` en `app/` | Solo condiciones fijas de índices y valores por defecto de las tablas; nunca con datos de entrada |
| Rutas locales, correos o IPs en lo versionado | Solo las IPs de documentación (`203.0.113.x`, `198.51.100.x`, RFC 5737) de los tests de rate limiting |
| Secret scanning y push protection de GitHub | Activados (consultado con `gh api`), además de Dependabot |
| Imágenes y acciones | Imagen de Python, base de datos y Redis fijadas por digest; ninguna acción de GitHub sin fijar por SHA |
| Lockfiles | `requirements.lock` y `requirements-dev.lock` con hashes (1254 y 2031 líneas con `--hash`) |
| Dockerfile | Usuario sin privilegios (`USER 10001:10001`); `.dockerignore` presente |
| Stack de contenedores | La base y Redis sin puertos publicados; la API solo en `127.0.0.1` |
| `pytest` (1061 tests) y `vitest` (176) | Verdes |

## Estado por apartado de AGENTS.md §8

"Hoy" = lo verifiqué en esta revisión. "Tests" = lo cubren tests que existen y pasan, pero no
volví a leer el código línea a línea.

| § | Tema | Estado | Evidencia |
|---|---|---|---|
| 8.1 | Claves y secretos | Cumple | gitleaks limpio y secret scanning activado (hoy) |
| 8.2 | Variables de entorno | Cumple | Ningún `os.environ` fuera de `config.py` (hoy); 13 tests de arranque en producción (tests); `METRICS_TOKEN` validado (7.1) |
| 8.3 | Rutas de administración | Cumple | `require_admin` a nivel de router; tests 401/403 (tests) |
| 8.4 | Autenticación | Cumple (tests) | Cookie de refresh `HttpOnly`, `Secure`, `SameSite=Strict` (hoy, en el código); el resto, por tests |
| 8.5 | Autorización de usuarios | No aplica | Los datos son de lectura para cualquier usuario autenticado; no hay recursos propios todavía |
| 8.6 | Validación de entradas | Cumple | `extra="forbid"`, rangos y ventanas acotadas; SQL solo con SQLAlchemy (hoy, por búsqueda) |
| 8.7 | XSS | Cumple | Sin sinks peligrosos (hoy); regla de ESLint con su test; tests con nombres hostiles en las fichas y paneles |
| 8.8 | Rate limiting | **Parcial** | Capa de la app, con tests. **La capa del proxy no existe** (no hay proxy) |
| 8.9 | Endpoints | Cumple | `test_deny_by_default` recorre todas las rutas; `/ready` añadido a la lista blanca con justificación; `/metrics` con token propio; Origin del WebSocket validado (hoy, en el código) |
| 8.10 | CORS | Cumple (tests) | Lista explícita; test de origen no listado |
| 8.11 | Cabeceras | **Parcial** | API: middleware con tests. Frontend: **CSP añadida en este PR** (ver hallazgo 2). **Proxy (HSTS, redirección, ocultar versión): no existe** |
| 8.12 | Modo de depuración | Cumple | Sin `debug`; sin source maps (`sourcemap: false`); `/docs` público por decisión |
| 8.13 | Dependencias | Cumple | pip-audit y npm audit limpios; lockfiles con hashes; Dependabot activado (hoy) |
| 8.14 | Paquetes sin usar | Cumple (revisión manual) | Las tareas 5.3 a 7.3 no añadieron ninguna dependencia; no se ha ejecutado `deptry` |
| 8.15 | Archivos expuestos | Cumple | `.gitignore` cubre `.env*`, volcados, copias cifradas y `backups/`; `.dockerignore` presente |
| 8.16 | Base de datos | **Parcial** | Sin puertos publicados, mínimo privilegio con tests, copias cifradas con restauración probada (7.2). **Faltan copias automáticas** y no hay despliegue donde medirlo |
| 8.17 | Hash de contraseñas | Cumple (tests) | Argon2id |
| 8.18 | Historial de Git | Cumple | Solo correos `noreply`; gitleaks en pre-commit y en CI (hoy) |
| 8.19 | Auditoría integral | Esta revisión | CI con gitleaks, pip-audit, tests de autorización y ruff `S` |
| 8.20 | Precisión | Cumple | Cada tarea cerró con tests, tipos, lint y CI en verde |

## Hallazgos abiertos

1. **No existe el entorno de producción** (ADR-0011: demo en Pages; ADR-0012: recolector en
   Actions). Mientras no exista, no se pueden aplicar ni probar: HSTS, redirección a HTTPS,
   ocultar la versión del servidor, rate limiting global por IP, el bloqueo de `/metrics` desde
   Internet y `frame-ancestors 'none'`. Todo eso lo exige AGENTS.md §8.8 y §8.11 y **está sin
   hacer**.
2. **CSP del frontend: añadida y verificada en la demo; la app completa, sin probar.** Faltaba
   por completo. Se genera en la compilación (`web/csp.ts`) desde la configuración (API y tiles) y
   se pone en un `<meta>` (GitHub Pages no deja mandar cabeceras). La primera versión **bloqueaba
   el worker de MapLibre** (`worker-src blob:` no bastaba: MapLibre 6 lo sirve como fichero del
   propio origen); se detectó abriendo la demo construida en Chrome y leyendo la consola, y se
   corrigió. **Verificación con la versión corregida**: Chrome controlado por el protocolo de
   depuración (CDP), esperando 18 s **en tiempo real** y leyendo la consola y la red: **0
   violaciones de CSP y 0 peticiones bloqueadas**, y la demo se pinta entera: mapa con tiles, los 8
   buques, las dos zonas de entrada con sus etiquetas, leyenda y controles. (Las primeras capturas
   salían en blanco al azar porque `--virtual-time-budget` no espera a la red; no era la CSP.)
   **Sin probar**: la aplicación completa con la API (login, llamadas REST y el WebSocket
   `/ws/live` bajo `'self'`), porque exige levantar la pila y servir el frontend compilado detrás
   del mismo origen que la API; y `frame-ancestors`, que un `<meta>` ignora y necesita una
   cabecera.
3. **Copias de seguridad sin programar** (`docs/BACKUP.md`): no hay dónde. Y nunca se ha
   restaurado una copia con datos reales.
4. **Validación con datos reales sin hacer (tarea 5.7)**: la precisión de los polígonos, los
   umbrales de los tránsitos (timeout de 30 min), de los fondeaderos (15 min, 1 nudo) y del enlace
   de esperas (24 h) no están contrastados. No es un fallo de seguridad pero sí de corrección, y
   quien lea las estadísticas debe saberlo.
5. **Zona gris en los términos de GitHub** para el recolector de AIS (ADR-0012): ya documentada;
   se apaga cambiando una variable.
6. **No revisado línea a línea hoy**: autenticación (8.4), autorización de administración (8.3),
   CORS (8.10) y hash de contraseñas (8.17) se dan por buenos por sus tests, no por una lectura
   del código en esta revisión.
7. **Las capturas** de `docs/media/`: solo he visto hoy la de estadísticas (datos inventados,
   sin cabecera de aplicación ni del navegador). Las de la Fase 4 y el GIF no se han vuelto a
   revisar en busca de datos personales.
8. **Las reglas de alerta** (`docker/prometheus/`) están validadas con `promtool`, pero no
   conectadas a ningún Prometheus ni a un canal de aviso.

## Qué haría falta para cerrar la 7.6

Elegir dónde se despliega y, con ese entorno: configurar el proxy (HSTS, redirección, límites,
bloqueo de `/metrics`, `frame-ancestors`), repetir esta revisión contra él, programar las copias y
restaurar una real, abrir la app con la CSP en un navegador, y revisar las capturas y el GIF.
