# Recorridos de Ecobici

**Origen:** https://data.buenosaires.gob.ar/dataset/bicicletas-publicas

**Publica:** Gobierno de la Ciudad de Buenos Aires, portal Buenos Aires Data.

**Licencia:** CC BY 2.5 AR (hay que citar la fuente).

**Fuente primaria:** Secretaría de Transporte y Obras Públicas.

**Actualización:** mensual. El portal publica un recurso "Recorridos Realizados" por año, de 2010 a 2026.

## Archivos

Un CSV por año, de `trips_2010.csv` a `trips_2026.csv` (2026 llega hasta el 30 de septiembre: al 14 de noviembre de 2026 el portal no había publicado octubre). Cada fila es un viaje: fecha y estación de origen, fecha y estación de destino, duración, usuario y, desde 2019, modelo de bicicleta.

Los archivos `trips.partNNN.rar` son los mismos CSV comprimidos y partidos en volúmenes; los CSV no se versionan (ver `.gitignore`).

## A tener en cuenta

- El formato cambia según el año: nombres de columnas, sufijo `BAEcobici` en los identificadores (2019–2023 y 2025–2026, no en 2024), duración como intervalo (hasta 2018) o en segundos con coma de miles (desde 2019).
- En 2019 la longitud de la estación de destino trae la latitud.
- Los archivos no están ordenados por fecha.
- `trips_2024_baddata.csv` no está depurado como los demás: tiene 37.618 viajes de duración 0 y 324.388 de menos de un minuto (el 9%), que en los otros años no aparecen. También le faltan 3.379 fechas de destino y el identificador de usuario viene con `.0`.
- Entre 2022 y 2026 hay entre 197 y 687 viajes por año de más de 24 horas.
- En 2025 y 2026 algunos viajes traen la estación con coordenadas fuera de la Ciudad (223 y 112 viajes).
- En 2026 el género no informado figura como `Não identificado` en lugar de `OTHER`.
