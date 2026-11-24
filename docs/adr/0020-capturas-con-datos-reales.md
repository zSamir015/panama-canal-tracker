# ADR-0020: Capturas estáticas con datos reales de AISStream

- **Fecha**: 2026-11-22
- **Estado**: Aceptada. Complementa al ADR-0008, que sigue vigente.

## Contexto
El ADR-0008 decidió que los datos de AISStream solo los ven usuarios con sesión: AISStream no
publica términos de uso, su documentación asume que el servidor reenvía los datos a sus propios
clientes y nada dice sobre mostrarlos a cualquiera. Desde entonces el README ilustra la interfaz
solo con datos simulados.

El proyecto está terminado y recoge datos reales desde el 2026-11-07 (worker local y recolector de
GitHub, `docs/VALIDATION.md`). Las capturas simuladas no enseñan cómo se comporta la aplicación
con la cobertura real, que es parcial: pocos buques, esperas largas en fondeadero y rutas con
huecos. Para valorar el trabajo conviene verlo con datos reales.

Los mensajes AIS los emiten los buques en abierto, pero el nombre y el MMSI de una embarcación de
recreo, de un velero o de un pesquero pueden identificar a una persona, y una ruta de varios días
permite seguirla.

## Decisión
El README puede incluir **capturas estáticas** con datos reales, con estas condiciones:

1. Son imágenes fijas de un momento concreto o grabaciones cortas, ya terminadas, de la interfaz
   (un clip de un minuto como mucho). No hay flujo, ni modo anónimo, ni enlace a datos en vivo: lo
   decidido en el ADR-0008 no cambia. Un clip es una captura que dura unos segundos, no un acceso
   a los datos.
2. Se enmascara el nombre y el MMSI de las embarcaciones clasificadas como recreo, pesca u otro tipo
   no comercial. Los buques de carga, tanqueros y de pasajeros se enseñan tal como los emite AIS.
3. Una ruta solo se publica de un buque comercial. Nunca la de un velero o una embarcación personal.
4. Cada captura indica la fuente (AISStream) y que la cobertura es parcial.
5. No salen cuentas, correos, rutas locales ni nada de la sesión: solo la ventana de la aplicación.
   Las capturas se hacen con una cuenta desechable que se borra al terminar.
6. Si AISStream publica términos que lo impidan, o su titular lo pide, se retiran las imágenes y se
   limpia el historial de la rama principal si procede.

Las capturas con datos reales conviven con las simuladas: las simuladas siguen siendo la referencia
de lo que hace la interfaz con una flota completa, y las reales, de lo que hace con la cobertura
gratuita.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Solo capturas simuladas | No enseñan el comportamiento con la cobertura real, que es lo que más pesa al evaluar el proyecto |
| Capturas reales sin enmascarar | Identifican y permiten seguir a personas propietarias de embarcaciones personales |
| Demo pública con datos reales | Contradice el ADR-0008: sin términos explícitos es la opción de más riesgo |

## Consecuencias
- Las capturas reales son `docs/media/real-ais-*.png`. Son la lista de ficheros a retirar si hiciera
  falta.
- Los clips con datos reales son `docs/media/real-ais-*.mp4`, y se retiran igual que las imágenes.
  Se graban sin la lista de buques y sin los tooltips del mapa, y solo se abre la ficha de un buque
  comercial.
- El enmascarado se hace al capturar, sobre la interfaz, y queda dicho en el pie de cada imagen.
- Los datos de la base local siguen sin publicarse: ni los ficheros del recolector ni las copias de
  seguridad salen de la máquina.
