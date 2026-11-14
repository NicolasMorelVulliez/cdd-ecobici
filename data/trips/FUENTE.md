# Recorridos de Ecobici

**Origen:** https://data.buenosaires.gob.ar/dataset/bicicletas-publicas

**Publica:** Gobierno de la Ciudad de Buenos Aires, portal Buenos Aires Data.

**Licencia:** CC BY 2.5 AR (hay que citar la fuente).

**Fuente primaria:** Secretaría de Transporte y Obras Públicas.

**Actualización:** mensual. El portal publica un recurso "Recorridos Realizados" por año, de 2010 a 2026.

## Archivos

Un CSV por año, de `trips_2010.csv` a `trips_2026.csv` (2026 llega hasta fines de junio). Cada fila es un viaje: fecha y estación de origen, fecha y estación de destino, duración, usuario y, desde 2019, modelo de bicicleta.

Los archivos `trips.partNNN.rar` son los mismos CSV comprimidos y partidos en volúmenes; los CSV no se versionan (ver `.gitignore`).

## A tener en cuenta

- El formato cambia según el año: nombres de columnas, sufijo `BAEcobici` en los identificadores, duración como intervalo (hasta 2018) o en segundos con coma de miles (desde 2019).
- En 2019 la longitud de la estación de destino trae la latitud.
- `trips_2024_baddata.csv` tiene viajes de duración 0.
- `Trips_2025.csv` incluye filas de otros períodos.
