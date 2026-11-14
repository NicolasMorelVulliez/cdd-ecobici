"""Captura el estado de las estaciones de Ecobici (bicicletas y anclajes disponibles).

El feed del operador solo informa el estado del momento, sin historial. Este script lo consulta y
agrega una fila por estación a un CSV diario, para poder comprobar después contra la realidad qué
estaciones se quedan vacías o saturadas.

Uso:
    python src/capture_station_status.py                  # una sola captura
    python src/capture_station_status.py --interval 600   # una captura cada 10 minutos, sin fin

Solo usa la biblioteca estándar.
"""

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATUS_URL = "https://buenosaires.publicbikesystem.net/customer/gbfs/v2/pt/station_status"

# Buenos Aires no tiene horario de verano: se fija UTC-3 para no depender de la base de zonas
# horarias, que en Windows no viene con Python.
BUENOS_AIRES = timezone(timedelta(hours=-3))

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "stations" / "status"

COLUMNS = [
    "captured_at",
    "station_id",
    "num_bikes_available",
    "num_bikes_disabled",
    "num_docks_available",
    "num_docks_disabled",
    "status",
    "is_renting",
    "is_returning",
    "last_reported",
]


def fetch_status(timeout: float = 30) -> list[dict]:
    """Descarga el estado actual de todas las estaciones.

    :param timeout: segundos de espera máxima de la solicitud.
    :returns: una lista con un diccionario por estación, tal como lo publica el feed.
    """
    request = urllib.request.Request(STATUS_URL, headers={"User-Agent": "python-urllib"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["data"]["stations"]


def to_local_iso(epoch: int | None) -> str:
    """Convierte segundos desde 1970 a fecha y hora de Buenos Aires.

    :param epoch: instante en segundos; puede faltar en el feed.
    :returns: la fecha en formato ISO sin zona, o cadena vacía si no hay dato.
    """
    if not epoch:
        return ""
    return datetime.fromtimestamp(epoch, BUENOS_AIRES).strftime("%Y-%m-%dT%H:%M:%S")


def append_snapshot(stations: list[dict], output_dir: Path) -> Path:
    """Agrega una captura al CSV del día.

    :param stations: estado de las estaciones devuelto por el feed.
    :param output_dir: carpeta donde se guardan los CSV diarios.
    :returns: la ruta del archivo donde se escribió.
    """
    now = datetime.now(BUENOS_AIRES)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"status_{now:%Y-%m-%d}.csv"
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        if is_new:
            writer.writerow(COLUMNS)
        captured_at = now.strftime("%Y-%m-%dT%H:%M:%S")
        for station in stations:
            writer.writerow(
                [
                    captured_at,
                    station.get("station_id"),
                    station.get("num_bikes_available"),
                    station.get("num_bikes_disabled"),
                    station.get("num_docks_available"),
                    station.get("num_docks_disabled"),
                    station.get("status"),
                    int(bool(station.get("is_renting"))),
                    int(bool(station.get("is_returning"))),
                    to_local_iso(station.get("last_reported")),
                ]
            )
    return path


def capture_once(output_dir: Path) -> bool:
    """Hace una captura y la guarda.

    :param output_dir: carpeta donde se guardan los CSV diarios.
    :returns: True si se guardó; False si el feed falló.
    """
    try:
        stations = fetch_status()
    except Exception as error:  # la red puede fallar; no se corta una captura periódica por eso
        print(f"{datetime.now(BUENOS_AIRES):%Y-%m-%d %H:%M:%S} error: {error}", file=sys.stderr)
        return False
    path = append_snapshot(stations, output_dir)
    empty = sum(1 for station in stations if station.get("num_bikes_available") == 0)
    full = sum(1 for station in stations if station.get("num_docks_available") == 0)
    print(
        f"{datetime.now(BUENOS_AIRES):%Y-%m-%d %H:%M:%S} {len(stations)} estaciones, "
        f"{empty} sin bicicletas, {full} sin anclajes -> {path.name}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Captura el estado de las estaciones de Ecobici.")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="segundos entre capturas; si se omite, hace una sola y termina",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="carpeta de salida")
    arguments = parser.parse_args()

    if arguments.interval <= 0:
        return 0 if capture_once(arguments.output) else 1

    while True:
        started = time.monotonic()
        capture_once(arguments.output)
        # Se descuenta lo que tardó la captura para que el intervalo no se vaya corriendo.
        time.sleep(max(0, arguments.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    sys.exit(main())
