# Clima horario de Buenos Aires

**Origen:** https://open-meteo.com/en/docs/historical-weather-api

**Publica:** Open-Meteo (archivo histórico basado en reanálisis meteorológico). Es gratuito y no pide clave.

**Licencia:** CC BY 4.0 (hay que citar a Open-Meteo).

**Descargado:** 2026-11-14 con `src/download_weather.py`, que arma la consulta y reemplaza el archivo. Para cambiar el período o las variables, se edita ese script.

## Archivos

| Archivo | Contenido |
|---|---|
| `open_meteo_horario_2019_2026.csv` | 68.664 horas, del 2019-01-01 al 2026-10-31, sin valores vacíos: temperatura, sensación térmica, humedad, precipitación, lluvia, viento, ráfagas, nubosidad y código de estado del tiempo (WMO). |

## A tener en cuenta

- Las tres primeras líneas del archivo son metadatos (coordenadas y zona horaria); la tabla empieza en la cuarta.
- La hora está en horario de Buenos Aires, igual que los recorridos.
- Es un solo punto para toda la ciudad (centro geográfico de CABA). El servicio lo ajusta a la celda más cercana de su grilla: -34,622 / -58,409.
- Es un dato modelado, no la medición de una estación meteorológica. Para validar días puntuales se puede comparar contra el SMN.
