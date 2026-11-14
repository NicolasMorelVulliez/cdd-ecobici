# Estaciones de transporte masivo de la Ciudad de Buenos Aires

**Origen:** cuatro datasets del portal Buenos Aires Data:

- Subte: https://data.buenosaires.gob.ar/dataset/subte-estaciones (responsable: Subterráneos de Buenos Aires, SBASE; actualización anual).
- Ferrocarril: https://data.buenosaires.gob.ar/dataset/estaciones-ferrocarril (responsable: Ministerio de Desarrollo Urbano y Transporte, Secretaría de Transporte; actualización trimestral).
- Premetro: https://data.buenosaires.gob.ar/dataset/premetro (responsable: SBASE; actualización trimestral).
- Metrobus: https://data.buenosaires.gob.ar/dataset/metrobus (responsable: Secretaría de Transporte y Obras Públicas, Jefatura de Gabinete; actualización eventual).

**Publica:** Gobierno de la Ciudad de Buenos Aires, portal Buenos Aires Data.

**Licencia:** CC BY 2.5 AR en los cuatro datasets (hay que citar la fuente).

**Descargado:** 2026-11-14. Cada archivo es idéntico (MD5) al que el portal sirve desde:

- https://cdn.buenosaires.gob.ar/datosabiertos/datasets/sbase/subte-estaciones/estaciones_de_subte.geojson
- https://cdn.buenosaires.gob.ar/datosabiertos/datasets/transporte-y-obras-publicas/estaciones-ferrocarril/estaciones_ferroviarias.geojson
- https://cdn.buenosaires.gob.ar/datosabiertos/datasets/sbase/premetro/estaciones_de_premetro.geojson
- https://cdn.buenosaires.gob.ar/datosabiertos/datasets/transporte-y-obras-publicas/metrobus/estaciones-de-metrobus.geojson

Según el portal, los datasets de subte, ferrocarril y premetro se actualizaron por última vez el 13 de noviembre de 2026, y el de Metrobus el 23 de junio de 2026.

## Archivos

Todos son GeoJSON de puntos, con coordenadas en longitud/latitud (CRS84) y codificación UTF-8.

| Archivo | Contenido |
|---|---|
| `estaciones_de_subte.geojson` | 90 estaciones de las líneas A, B, C, D, E y H: `id`, `estacion` (nombre) y `linea`. Todas dentro de CABA. |
| `estaciones_ferroviarias.geojson` | 301 estaciones de tren del área metropolitana: `id`, `idecaba`, `nombre`, `linea`, `ramal`, `barrio`, `comuna`, `localidad` y `partido`. Solo 43 están en CABA. |
| `estaciones_de_premetro.geojson` | 18 estaciones del premetro: `id`, `nombre`, `ramal`, `dirreccion` (así, con doble r), `barrio` y `comuna`. Todas dentro de CABA. |
| `estaciones-de-metrobus.geojson` | 390 paradas de Metrobus: `CALLE`, `ALT PLANO`, `DIRECCION`, `coord_X`, `coord_Y`, `COMUNA`, `BARRIO`, las líneas de colectivo que paran (`L1` a `L6`, con su sentido en `l1_sen` a `l6_sen`) y `NOMBRE PAR` (nombre de la parada). Todas dentro de CABA. |

## A tener en cuenta

- **Ferrocarril incluye el conurbano.** De las 301 estaciones, 231 caen fuera del rectángulo de CABA (latitud entre -34,71 y -34,52; longitud entre -58,54 y -58,33) y 70 caen adentro. Pero el rectángulo no sigue el límite real: 27 de esas 70 son del conurbano pegado a la General Paz o al Riachuelo (Florida, Munro, Sáenz Peña, Lanús, Avellaneda, etc.). Las 43 de CABA son las que tienen `barrio` y `comuna` cargados; las del conurbano tienen esos campos vacíos y traen `localidad`. No se borró ninguna.
- En ferrocarril, `ramal` solo está cargado para las 43 estaciones de CABA. `partido` repite el valor de `localidad` (por ejemplo, "Adrogué" en lugar de "Almirante Brown"), así que no sirve para identificar el partido. `idecaba` tiene valores repetidos; el identificador único es `id`.
- Las estaciones de combinación aparecen una vez por línea: en subte hay dos "Retiro" (C y E) y dos "Pueyrredon" (B y H); en tren hay tres "Retiro" (Mitre, San Martín y Belgrano Norte), con puntos separados entre 90 y 230 m. Hay dos "Juan Vucetich" en tren que son estaciones distintas (Roca y Urquiza, ambas en el conurbano).
- En Metrobus cada registro es un punto de parada para un grupo de líneas de colectivo, no una estación: una misma estación puede tener varios puntos a pocos metros (por ejemplo, la parada "CHILE" de Paseo Colón tiene cuatro). `NOMBRE PAR` suele ser la calle transversal, así que el mismo nombre puede repetirse en corredores distintos. Hay 140 nombres distintos y 38 paradas sin nombre. El sentido (`l1_sen` a `l6_sen`) viene como "I" o "V" (una vez "v" en minúscula), sin explicación en el portal, y a veces vacío. `coord_X` y `coord_Y` son texto con coma decimal; coinciden con la geometría, que es la que conviene usar. El campo `CALLE` tiene errores de tipeo ("INTEDENTE FRANCISCO RABANAL AV.").
- El portal también publica estos datos en CSV, pero los de subte y ferrocarril traen la ubicación como texto WKT (`POINT (lon lat)`) y no en columnas de latitud y longitud, así que se guardó el GeoJSON.
- Es una foto del día de la descarga: no indica desde cuándo funciona cada estación.
