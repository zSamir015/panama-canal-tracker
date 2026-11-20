# ADR-0018: Capa satelital gratuita con Esri World Imagery y modo oscuro con OpenFreeMap

- **Fecha**: 2026-11-19
- **Estado**: Aceptada

## Contexto

La UI inicial mostraba únicamente el estilo vectorial claro de OpenFreeMap (`liberty`, ADR-0010).
En la operación del Canal de Panamá, ver las esclusas, rompeolas, islas de Lago Gatún y áreas de
fondeadero sobre fotografía satelital facilita confirmar visualmente si un buque está en el canal
navegable, atracado o fondeado fuera de tierra, y el modo oscuro reduce la fatiga visual en guardias
o uso prolongado.

El requisito del proyecto (ADR-0010, ADR-0011) exige mantener una arquitectura **sin API keys ni
facturación** que funcione tanto en local como en la demo estática de GitHub Pages (`VITE_DEMO=true`).

## Decisión

1. **Capa satelital sin API key (`Esri World Imagery`)**:
   - Se añade un conmutador `Mapa` / `Satélite` en el visor MapLibre GL.
   - En modo `Satélite` se usa el servicio público ráster
     `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
     con su atribución obligatoria (`Tiles © Esri — Esri, Maxar, Earthstar Geographics, and the GIS
     User Community`) y glifos de fuentes de OpenFreeMap (`tiles.openfreemap.org`) para las etiquetas
     de las zonas de entrada.
2. **Estilo oscuro (`OpenFreeMap dark`)**:
   - El estilo vectorial `Mapa` usa `https://tiles.openfreemap.org/styles/liberty` en modo claro y
     `https://tiles.openfreemap.org/styles/dark` en modo oscuro (mismo origen que ADR-0010), salvo
     si se ha configurado un `VITE_MAP_STYLE_URL` personalizado.
3. **Política de Seguridad de Contenidos (`web/csp.ts`)**:
   - Se autoriza explícitamente `https://server.arcgisonline.com` en `img-src` y `connect-src`, sin
     comodines (`*`) ni llaves embebidas.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Google Map Tiles API (`tile.googleapis.com`) | Requiere clave de API de Google Cloud con facturación activa; no encaja con una demo estática pública sin secretos ni consumo medido (ADR-0010/0011) |
| Tiles no oficiales (`mt*.google.com`) | Uso no autorizado fuera de los términos de servicio de Google Maps y frágil ante bloqueos |
| Sentinel-2 Cloudless (EOX) sin etiquetas | Menor resolución de detalle en cámaras de esclusas y buques frente a World Imagery |

## Consecuencias

- La vista satelital de alta resolución funciona sin configuración adicional ni credenciales en local y
  en GitHub Pages.
- El cambio de mapa base conserva todas las fuentes y capas en vivo (zonas de entrada, estela y
  buques) adaptando halo y color de trazo para mantener contraste sobre fondo oscuro o vegetación.
- Si en el futuro se cambia el proveedor satelital, basta actualizar el origen en `web/csp.ts` y la
  definición del estilo en `web/src/map/mapStyles.ts`.
