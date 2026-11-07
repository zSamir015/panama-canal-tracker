# ADR-0014: `/metrics` con token propio y formato de Prometheus escrito a mano

- **Fecha**: 2026-11-06
- **Estado**: Aceptada
- **Modifica**: la frase "`/metrics` no se expone a Internet (solo red interna)" de AGENTS.md §8.9

## Contexto
La tarea 7.1 pide `/metrics` para Prometheus, `/ready` y una alerta si el worker pasa más de
5 minutos sin mensajes. AGENTS.md dice que `/metrics` va solo por la red interna, pero la API no
puede saber desde dónde le llegan las peticiones: depende de cómo se configure el proxy, y un
despliegue mal configurado la dejaría abierta. Además, lo que exporta (estado del worker, número
de tránsitos) no es secreto pero tampoco hay motivo para publicarlo.

## Decisión
- `/metrics` exige `Authorization: Bearer <METRICS_TOKEN>`: un token estático de la configuración
  (`SecretStr`, mínimo 32 bytes), comparado en tiempo constante. Prometheus lo soporta
  (`authorization: credentials`). **Sin token configurado, el endpoint responde 401 siempre**
  (denegar por defecto), con el mismo cuerpo que cualquier ruta protegida. El proxy sigue sin
  tener que exponerlo: el token es una segunda capa, no sustituye a la primera.
- Un JWT de usuario **no** vale para `/metrics`, ni el token de métricas vale para la API.
- `/ready` es público, igual que `/health`: solo dice `ok` o `failed` por dependencia, sin
  mensajes de error, y lo usa el orquestador.
- El formato de exposición de texto de Prometheus se escribe a mano
  (`app/services/metrics.py`) en vez de usar `prometheus_client`. Son unas pocas métricas con
  nombres y etiquetas fijos, y una dependencia más es algo más que auditar (AGENTS.md §8.14).
  Un test comprueba que cada línea tiene la forma del formato.
- Las métricas del worker salen del estado que ya publica en Redis (3.5): la API no se conecta al
  worker ni a AISStream.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| `/metrics` sin autenticación, confiando en el proxy | Un fallo de configuración lo abre a Internet sin que nada lo avise |
| JWT de un usuario admin para Prometheus | Caduca a los 15 minutos y obliga a Prometheus a renovar sesión |
| `prometheus_client` | Ofrece métricas de proceso y de peticiones HTTP, pero añade una dependencia y aquí no hacen falta |
| Puerto aparte solo para `/metrics` | Otro proceso o puerto que desplegar y proteger |

## Consecuencias
- **No hay métricas de peticiones HTTP** (conteo, latencia) ni de proceso: habría que escribirlas
  a mano o adoptar `prometheus_client` con otro ADR.
- La API lee Redis y la base en cada scrape; con un scrape cada 15-60 s es despreciable. Si una
  falla, el scrape no falla: `canal_dependency_up` lo dice y las métricas que dependían de ella
  se omiten.
- Los contadores del worker (`*_total`) se reinician cuando este arranca.
- Hay que repartir el token a Prometheus y rotarlo como cualquier secreto.
