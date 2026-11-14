# Clima horario de Buenos Aires

**Origen:** https://open-meteo.com/en/docs/historical-weather-api

**Publica:** Open-Meteo (archivo histórico basado en reanálisis meteorológico). Es gratuito y no pide clave.

**Licencia:** CC BY 4.0 (hay que citar a Open-Meteo).

**Descargado:** 2026-11-14, con esta consulta:

https://archive-api.open-meteo.com/v1/archive?latitude=-34.6&longitude=-58.44&start_date=2019-01-01&end_date=2026-06-30&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,rain,wind_speed_10m,wind_gusts_10m,cloud_cover,weather_code&timezone=America%2FArgentina%2FBuenos_Aires&format=csv

## Archivos

| Archivo | Contenido |
|---|---|
| `open_meteo_horario_2019_2026.csv` | 65.712 horas, del 2019-01-01 al 2026-06-30, sin valores vacíos: temperatura, sensación térmica, humedad, precipitación, lluvia, viento, ráfagas, nubosidad y código de estado del tiempo (WMO). |

## A tener en cuenta

- Las tres primeras líneas del archivo son metadatos (coordenadas y zona horaria); la tabla empieza en la cuarta.
- La hora está en horario de Buenos Aires, igual que los recorridos.
- Es un solo punto para toda la ciudad (centro geográfico de CABA). El servicio lo ajusta a la celda más cercana de su grilla: -34,622 / -58,409.
- Es un dato modelado, no la medición de una estación meteorológica. Para validar días puntuales se puede comparar contra el SMN.
