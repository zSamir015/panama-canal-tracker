# ADR-0002: AISStream.io como fuente de datos AIS

- **Fecha**: 2026-10-15
- **Estado**: Aceptada

## Contexto
Se necesita un stream de posiciones de buques sobre el área del Canal de Panamá, gratuito y
legalmente usable en un proyecto público de portafolio.

## Decisión
Usar **AISStream.io** (WebSocket, gratis con API key) con suscripción por bounding box del área
del Canal. Detalles y reglas en `docs/DATA_SOURCES.md`.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| MarineTraffic / VesselFinder | APIs comerciales de pago; scraping viola sus términos |
| ACP (EVTMS/VUMPA) | acceso restringido a la industria, sin API pública |
| OpenSky Network | es ADS-B (aviación), no AIS |
| NOAA AIS histórico | cubre EE. UU., no Panamá |

## Consecuencias
- Cobertura solo terrestre (~40 NM), sin histórico (nuestra DB lo construye), una sola conexión
  por key, prohibido conectar desde el navegador.
- El worker es un componente crítico: su robustez define la calidad del histórico (ADR-0004).
- Se necesita `scripts/ais_simulator.py` para desarrollo y CI sin depender del servicio.
- Pendiente: confirmar los términos de uso para una demo pública (tarea 3.7).
