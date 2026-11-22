# Documentación

El README de la raíz presenta el proyecto. Esta carpeta es el detalle, ordenada por lo que se
quiere saber.

## Para entender el sistema

| Documento | Contenido |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Componentes, flujo de datos, modelo de datos y lógica de dominio |
| [API_DESIGN.md](API_DESIGN.md) | Contrato REST y WebSocket |
| [DATA_SOURCES.md](DATA_SOURCES.md) | AISStream, zonas geográficas, límites del servicio y cobertura |
| [adr/](adr/README.md) | Decisiones de arquitectura y por qué se tomaron |

## Para ejecutarlo y mantenerlo

| Documento | Contenido |
|---|---|
| [OPERATIONS.md](OPERATIONS.md) | Qué corre y dónde, arranque, comprobaciones, rotación de secretos y problemas conocidos |
| [LOCAL_WORKER_MAC.md](LOCAL_WORKER_MAC.md) | Worker continuo en macOS con `launchd` |
| [BACKUP.md](BACKUP.md) | Copias cifradas, restauración, retención y programación |
| [AIS_COLLECTOR.md](AIS_COLLECTOR.md) | Recolector de GitHub Actions, replay e importación a la base local |

## Para evaluar la calidad y los límites

| Documento | Contenido |
|---|---|
| [VALIDATION.md](VALIDATION.md) | Validación con 14,9 días de AIS real: qué se puede y qué no se puede concluir |
| [LOAD_TEST.md](LOAD_TEST.md) | Prueba de carga del WebSocket con 500 clientes |
| [SECURITY_REVIEW.md](SECURITY_REVIEW.md) | Revisión de seguridad final y requisitos previos a un despliegue |
| [../SECURITY.md](../SECURITY.md) | Cómo informar de una vulnerabilidad |

## Historia del proyecto

| Documento | Contenido |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Las siete fases y lo que cerró cada una |
| [../CHANGELOG.md](../CHANGELOG.md) | Cambios por versión |
| [ENGINEERING.md](ENGINEERING.md) | Convenciones de código, pruebas, seguridad y flujo de trabajo |

Las capturas y animaciones están en `media/`.
