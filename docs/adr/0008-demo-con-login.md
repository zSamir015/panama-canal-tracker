# ADR-0008: Datos de AISStream solo para usuarios con sesión

- **Fecha**: 2026-10-21
- **Estado**: Aceptada

## Contexto
La tarea 3.7 pedía revisar si los términos de AISStream permiten mostrar sus datos en una demo
pública y decidir si sería pública, con login o con retraso. Revisión del 2026-10-21:

- **No hay términos de uso publicados.** `https://aisstream.io/terms` responde 404; la web solo
  enlaza una política de privacidad (`https://aisstream.io/privacypolicy`), y ni la documentación
  (`https://aisstream.io/documentation`) ni su repositorio público (`github.com/aisstream`) dicen
  nada sobre redistribuir o mostrar los datos.
- **La documentación sí asume que se reenvían**: *"Direct browser connections are not permitted.
  Connect from your own server and proxy only the information each client needs."* Es nuestra
  arquitectura (worker → Redis → API → `/ws/live`).
- **Límites documentados**: 3 conexiones suscritas por cuenta y 3 por IP (usamos 1).
- Los mensajes AIS los emiten los buques en abierto, pero eso no dice nada de las condiciones del
  servicio que los agrega.

## Decisión
Los datos de buques solo los ven usuarios con sesión: todos los endpoints de `/api/v1/vessels` y
`/ws/live` exigen access token. **No habrá modo anónimo** (ni en tiempo real ni con retraso).

El registro sigue abierto, así que cualquiera puede crearse una cuenta y verlos: esto no hace los
datos privados. Lo que sí consigue es que no estén al alcance de buscadores ni de visitantes
anónimos, que cada acceso esté identificado y limitado por usuario (rate limiting, ADR-0007) y que
se pueda cortar el acceso a una cuenta si hiciera falta.

## Alternativas consideradas
| Opción | Por qué no (por ahora) |
|---|---|
| Pública en tiempo real | Sin términos explícitos, es la opción con más riesgo |
| Pública con 15 min de retraso y datos reducidos | Riesgo moderado y más código (dos modos de `/ws/live`) sin una base clara en los términos |
| Esperar a preguntar a AISStream | Se puede preguntar igualmente (`github.com/aisstream/issues`); mientras tanto, login |

## Consecuencias
- `/ws/live` (Fase 4) autentica en el primer mensaje, sin variante anónima.
- La demo del portafolio (Fase 4) es pública como web, pero el mapa pide registro; el GIF del
  README (4.9) enseña el mapa sin necesidad de cuenta.
- Si AISStream publica términos que lo permitan, o lo confirma, se puede revisar con un ADR nuevo.
