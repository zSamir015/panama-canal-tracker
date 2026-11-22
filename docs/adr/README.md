# Registro de decisiones de arquitectura

Cada decisión técnica relevante tiene su ADR. Una decisión nueva va en el siguiente número libre y,
si cambia otra, la anterior recibe una nota que enlaza a la nueva. No se reescribe una decisión ya
aceptada.

| ADR | Decisión | Estado |
|---|---|---|
| [0001](0001-stack-tecnico.md) | Stack técnico | Aceptada |
| [0002](0002-fuente-de-datos-ais.md) | AISStream.io como fuente de datos AIS | Aceptada |
| [0003](0003-librerias-de-autenticacion.md) | PyJWT y pwdlib (Argon2id) para autenticación | Aceptada |
| [0004](0004-worker-separado-y-redis.md) | Worker de ingesta como proceso separado y Redis pub/sub | Aceptada |
| [0005](0005-timescaledb-para-posiciones.md) | TimescaleDB para la serie temporal de posiciones | Aceptada |
| [0006](0006-mapa-web-maplibre.md) | Mapa en tiempo real con React + MapLibre GL en el mismo repositorio | Aceptada |
| [0007](0007-rate-limiting.md) | Librería de rate limiting | Aceptada |
| [0008](0008-demo-con-login.md) | Datos de AISStream solo para usuarios con sesión | Aceptada |
| [0009](0009-segunda-conexion-destinos-al-canal.md) | Segunda conexión a AISStream para buques con destino al Canal | Aceptada |
| [0010](0010-tiles-openfreemap.md) | Tiles del mapa con OpenFreeMap | Aceptada |
| [0011](0011-demo-estatica-github-pages.md) | Demo estática en GitHub Pages | Aceptada |
| [0012](0012-recolector-ais-en-github-actions.md) | Recolector AIS en GitHub Actions | Aceptada |
| [0013](0013-estadisticas-con-sql-y-agregados-sobre-posiciones.md) | Las estadísticas de tránsitos usan SQL; los agregados continuos, las posiciones | Aceptada |
| [0014](0014-metricas-con-token-y-exposicion-manual.md) | `/metrics` con token propio y formato de Prometheus escrito a mano | Aceptada |
| [0015](0015-copias-logicas-cifradas-con-gpg.md) | Copias lógicas cifradas con `pg_dump` y `gpg` | Aceptada |
| [0016](0016-sentido-de-entrada-por-rumbo.md) | El rumbo (COG) decide si un buque entra o sale por una zona de entrada | Aceptada |
| [0017](0017-v1-sin-entorno-de-produccion.md) | `v1.0.0` sin entorno de producción | Aceptada |
| [0018](0018-satelite-esri-world-imagery.md) | Capa satelital gratuita con Esri World Imagery y modo oscuro con OpenFreeMap | Aceptada |
| [0019](0019-recolector-continuo-y-worker-a-la-vez.md) | Recolector AIS continuo y ejecución simultánea con worker local | Aceptada |
| [0020](0020-capturas-con-datos-reales.md) | Capturas estáticas con datos reales de AISStream | Aceptada |
