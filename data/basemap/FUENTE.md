# Mapa base de la Ciudad de Buenos Aires

**Origen:** https://www.openstreetmap.org (teselas de https://tile.openstreetmap.org)

**Publica:** OpenStreetMap y sus colaboradores.

**Licencia:** los datos del mapa son © colaboradores de OpenStreetMap, bajo la licencia ODbL. Hay que mostrar esa atribución junto a cada mapa; el reporte y la aplicación ya la incluyen.

**Descargado:** 2026-11-14 con `src/download_basemap.py`.

## Archivos

| Archivo | Contenido |
|---|---|
| `caba.jpg` | Imagen de 2.816 × 3.072 píxeles (1,4 MB) armada con 132 teselas del nivel de zoom 14, pasada a grises y aclarada para que sirva de fondo. |
| `caba.json` | Límites de la imagen en longitud y latitud, para ubicarla debajo de las estaciones. |

## A tener en cuenta

- Es una imagen fija: se ve nítida hasta acercar unas cuatro veces el encuadre de la Ciudad entera, y a partir de ahí se pixela. Se eligió el nivel 14 porque con el 13 (42 teselas, 0,5 MB) se pixelaba apenas se acercaba al doble y no se leían las calles; el 15 cuadruplicaría las teselas y el peso.
- La imagen está en proyección Mercator y se dibuja sobre ejes de longitud y latitud. A la escala de la Ciudad la diferencia es de a lo sumo un píxel de la imagen.
- Los servidores de teselas de OpenStreetMap se sostienen con donaciones y no admiten descargas masivas. El script baja las 132 teselas una sola vez y con pausas de medio segundo; no conviene correrlo seguido.
- Se usa una imagen guardada y no un mapa en línea para que los mapas se vean sin conexión y sin depender de WebGL.
