# Mapa base de la Ciudad de Buenos Aires

**Origen:** https://www.openstreetmap.org (teselas de https://tile.openstreetmap.org)

**Publica:** OpenStreetMap y sus colaboradores.

**Licencia:** los datos del mapa son © colaboradores de OpenStreetMap, bajo la licencia ODbL. Hay que mostrar esa atribución junto a cada mapa; el reporte y la aplicación ya la incluyen.

**Descargado:** 2026-11-14 con `src/download_basemap.py`.

## Archivos

| Archivo | Contenido |
|---|---|
| `caba.jpg` | Imagen de 1.536 × 1.792 píxeles armada con 42 teselas del nivel de zoom 13, pasada a grises y aclarada para que sirva de fondo. |
| `caba.json` | Límites de la imagen en longitud y latitud, para ubicarla debajo de las estaciones. |

## A tener en cuenta

- Es una imagen fija: sirve para ver la Ciudad entera, pero al acercar mucho se pixela. Para más detalle hay que subir el nivel de zoom en el script, y la imagen pesa cuatro veces más por cada nivel.
- La imagen está en proyección Mercator y se dibuja sobre ejes de longitud y latitud. A la escala de la Ciudad la diferencia no se nota.
- Los servidores de teselas de OpenStreetMap se sostienen con donaciones y no admiten descargas masivas. El script baja las 42 teselas una sola vez y con pausas; no conviene correrlo seguido.
- Se usa una imagen guardada y no un mapa en línea para que los mapas se vean sin conexión y sin depender de WebGL.
