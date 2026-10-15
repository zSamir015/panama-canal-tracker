# ADR-0005: TimescaleDB para la serie temporal de posiciones

- **Fecha**: 2026-10-15
- **Estado**: Aceptada (validar en Fase 3 con volumen real)

## Contexto
`positions` es una serie temporal de alto volumen de escritura (cientos de mensajes por minuto,
de forma continua). El plan inicial proponía borrar posiciones antiguas, lo que contradice que
nuestra base de datos sea el único histórico disponible.

## Decisión
- Usar la extensión **TimescaleDB** junto a PostGIS en el mismo PostgreSQL.
- `positions` es una **hypertable** particionada por `received_at`.
- **Compresión** de chunks de más de 7 días.
- **Agregados continuos** para estadísticas (Fase 6) y para un histórico reducido
  (una posición cada 5 min) de datos de más de 90 días. No se borra el histórico, se compacta.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| PostgreSQL con particionado nativo | posible, pero compresión, retención y agregados se harían a mano |
| Borrar posiciones antiguas | se pierde el único histórico disponible |
| Base de series temporales separada (InfluxDB) | otra base que operar; se pierde el JOIN con PostGIS |

## Consecuencias
- La imagen de DB debe incluir TimescaleDB y PostGIS (existen imágenes oficiales de Timescale con
  ambas; confirmar la etiqueta exacta en la Fase 2).
- Las migraciones de Alembic deben crear la hypertable y las políticas con SQL explícito.
- El hosting de la DB debe permitir la extensión TimescaleDB (un VPS propio no tiene problema).
