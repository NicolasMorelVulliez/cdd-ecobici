"""Descarga el clima horario de Buenos Aires desde el archivo histórico de Open-Meteo.

Uso:
    python src/download_weather.py

Reemplaza data/weather/open_meteo_horario_2019_2026.csv. Solo usa la biblioteca estándar.
"""

import sys
import urllib.parse
import urllib.request
from pathlib import Path

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Centro geográfico de la Ciudad. Alcanza un solo punto: la Ciudad mide unos 15 km de lado y la
# grilla del reanálisis es más gruesa que eso.
LATITUDE = -34.6
LONGITUDE = -58.44

START_DATE = "2019-01-01"
# Límite de los datos del trabajo.
END_DATE = "2026-10-31"

VARIABLES = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "weather_code",
]

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "weather" / "open_meteo_horario_2019_2026.csv"
)


def build_url() -> str:
    """Arma la consulta al archivo histórico.

    :returns: la dirección completa, con la hora en horario de Buenos Aires y salida en CSV.
    """
    parameters = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": ",".join(VARIABLES),
        "timezone": "America/Argentina/Buenos_Aires",
        "format": "csv",
    }
    return f"{ARCHIVE_URL}?{urllib.parse.urlencode(parameters)}"


def main() -> int:
    url = build_url()
    request = urllib.request.Request(url, headers={"User-Agent": "python-urllib"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(content)
    print(f"{content.count(b'\n')} líneas -> {OUTPUT_PATH}")
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
