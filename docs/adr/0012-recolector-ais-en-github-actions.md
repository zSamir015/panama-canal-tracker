# ADR-0012: Recolector AIS en GitHub Actions

- **Fecha**: 2026-11-06
- **Estado**: Aceptada
- **Modifica**: la regla 6 de `AGENTS.md` (AISStream solo desde el proceso `worker`)

## Contexto
La detección de tránsitos (Fase 5) y su validación contra las estadísticas de la ACP (tarea 5.7)
necesitan días de posiciones AIS reales. La cobertura de AISStream en el Canal es escasa: la
medición del 2026-11-06 dio 11 posiciones de 10 buques en 5 minutos, y la de octubre dio cero
(`docs/DATA_SOURCES.md` §2b). Hay que acumular datos durante varios días, pero:

- no hay un servidor encendido: el despliegue en VPS se sustituyó por la demo en Pages
  (ADR-0011), y el equipo del dueño no está siempre encendido;
- el dueño no quiere pagar un servidor.

## Decisión
Un workflow programado de GitHub Actions (`.github/workflows/collect-ais.yml`) ejecuta
`scripts/ais_collect.py`: se conecta a AISStream con la suscripción del worker durante 340
minutos, escribe cada posición y dato estático válido en un JSON Lines, lo cifra con `gpg` y lo
sube como artefacto. Arranca una ventana nueva cada 6 horas.

- **Sin base de datos ni Redis**: el recolector usa solo el parser y escribe un fichero. El replay
  de la tarea 5.5 lee ese fichero con el mismo detector que se usa con datos simulados.
- **Mínimo de datos**: no guarda nombres ni destinos de buques; solo identificador, posición,
  rumbo y velocidad, y de los estáticos tipo y dimensiones.
- **Cifrado antes de subir**: el repositorio es público y los artefactos de un repositorio público
  los puede descargar cualquiera con cuenta de GitHub. Publicar posiciones AIS crudas podría
  chocar con los términos de AISStream (la tarea 3.7 solo revisó mostrarlas en el mapa).
- **Apagado por defecto**: solo corre si la variable de repositorio `AIS_COLLECT_ENABLED` vale
  `true`, para no fallar cada 6 horas antes de configurar los secretos.
- **Secretos** (`AISSTREAM_API_KEY` y `AIS_COLLECT_PASSPHRASE`) solo en los pasos que los usan.
  Actions fijadas por SHA y permisos mínimos.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| VPS de pago | Fiable, pero el dueño no quiere gastar dinero |
| Oracle Cloud o Google Cloud, capas gratuitas | Piden tarjeta para verificar la cuenta; los planes cambian |
| Worker en el equipo del dueño | Se pierde cobertura cada vez que se apaga o duerme |
| Worker completo en Actions, con base de datos | Una base temporal no persiste entre ventanas |

## Consecuencias
- **Cobertura casi continua, no total**: entre ventanas hay unos 15 minutos sin conexión, y GitHub
  puede retrasar los cron. Para estadísticas diarias es aceptable; para medir un tránsito concreto
  hay que mirar si cae en un hueco.
- **Zona gris en las condiciones de GitHub**: piden usar Actions para probar, desplegar y
  publicar el proyecto, no como servidor de uso general. Recolectar datos para validar la
  detección de tránsitos está cerca de ese uso, pero no está garantizado. Lo peor que puede pasar
  es que limiten Actions en el repositorio; el recolector se apaga cambiando una variable.
- **Los workflows programados se desactivan solos** tras 60 días sin actividad en el repositorio.
- **Una conexión más a AISStream**: el worker usa dos (ADR-0009). No ejecutar el recolector a la
  vez que el worker; si se arranca el worker, poner `AIS_COLLECT_ENABLED` en `false`.
- **Excepción a la regla 6 de `AGENTS.md`**: la key de AISStream se usa también desde
  `scripts/ais_coverage.py` y `scripts/ais_collect.py`, nunca desde el navegador ni desde la API.
- Los artefactos caducan a los 90 días. Se descargan y descifran en local (`data/`, fuera de git):
  ver `docs/AIS_COLLECTOR.md`.
