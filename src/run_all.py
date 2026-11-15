"""Ejecuta todo el trabajo en un solo paso, de los datos crudos a los modelos entrenados.

Uso:
    python src/run_all.py              # todo, y al final dice cómo abrir la aplicación
    python src/run_all.py --app        # todo, y al final abre la versión en Streamlit
    python src/run_all.py --offline    # sin volver a bajar el clima (usa el archivo que ya está)

Pasos: baja el clima, arma las tablas, hace el análisis exploratorio, agrupa las estaciones,
entrena los modelos, compara algoritmos, arma el reporte general (reports/informe.html) y la
aplicación (reports/app.html). Si un paso falla, se detiene ahí.
"""

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
TRIPS = ROOT / "data" / "trips"
WEATHER_FILE = ROOT / "data" / "weather" / "open_meteo_horario_2019_2026.csv"

REQUIRED_PACKAGES = ["pandas", "pyarrow", "openpyxl", "geopandas", "sklearn", "plotly", "streamlit", "PIL"]
# Archivos de recorridos que usa el trabajo. No están en el repositorio como CSV por su tamaño.
REQUIRED_TRIPS = [
    "trips_2019.csv", "trips_2020.csv", "trips_2021.csv", "trips_2022.csv", "trips_2023.csv",
    "trips_2024_baddata.csv", "Trips_2025.csv", "trips_2026.csv",
]

STEPS = [
    ("Armar las tablas de trabajo", "build_dataset.py"),
    ("Análisis exploratorio", "eda.py"),
    ("Agrupar las estaciones", "cluster_stations.py"),
    ("Entrenar los modelos de demanda", "train_demand.py"),
    ("Comparar algoritmos", "compare_models.py"),
    ("Armar el reporte general", "build_report.py"),
    ("Armar la aplicación", "build_app.py"),
]


def check_environment() -> list[str]:
    """Revisa que estén las librerías y los datos crudos antes de empezar.

    :returns: la lista de problemas encontrados; vacía si está todo.
    """
    problems = []
    missing = [name for name in REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        problems.append(
            f"Faltan librerías ({', '.join(missing)}). Instalalas con: python -m pip install -r requirements.txt"
        )
    absent = [name for name in REQUIRED_TRIPS if not (TRIPS / name).exists()]
    if absent:
        problems.append(
            f"Faltan recorridos en {TRIPS} ({', '.join(absent)}). "
            "Descomprimí trips.part001.rar en esa carpeta (los demás volúmenes se abren solos)."
        )
    return problems


def run_step(title: str, script: str) -> bool:
    """Corre un script del trabajo y muestra su salida.

    :param title: descripción del paso.
    :param script: nombre del archivo dentro de src/.
    :returns: True si terminó bien.
    """
    print(f"\n{'=' * 80}\n{title} ({script})\n{'=' * 80}", flush=True)
    started = time.time()
    # -X utf8 para que los acentos de la salida se vean bien en la consola de Windows.
    result = subprocess.run([sys.executable, "-X", "utf8", "-W", "ignore", str(SRC / script)], cwd=ROOT)
    print(f"-- {title}: {'listo' if result.returncode == 0 else 'FALLÓ'} en {time.time() - started:.0f} s", flush=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecuta todo el trabajo en un solo paso.")
    parser.add_argument("--offline", action="store_true", help="no vuelve a bajar el clima")
    parser.add_argument("--app", action="store_true", help="abre la versión en Streamlit al terminar")
    arguments = parser.parse_args()

    problems = check_environment()
    if problems:
        print("No se puede empezar:\n- " + "\n- ".join(problems))
        return 1

    started = time.time()
    if not arguments.offline:
        # Sin conexión no se corta el trabajo si ya hay un archivo de clima de una corrida anterior.
        if not run_step("Bajar el clima", "download_weather.py"):
            if not WEATHER_FILE.exists():
                print("No se pudo bajar el clima y no hay un archivo anterior.")
                return 1
            print("No se pudo bajar el clima; se sigue con el archivo que ya estaba.")
    for title, script in STEPS:
        if not run_step(title, script):
            return 1

    print(f"\nTodo listo en {(time.time() - started) / 60:.1f} minutos.")
    print(f"Reporte general: {ROOT / 'reports' / 'informe.html'}")
    print(f"Aplicación (se abre con doble clic): {ROOT / 'reports' / 'app.html'}")
    print(f"Gráficos sueltos: {ROOT / 'reports'}")
    command = [sys.executable, "-m", "streamlit", "run", str(SRC / "app.py")]
    if arguments.app:
        return subprocess.run(command, cwd=ROOT).returncode
    print("Para abrir la versión en Streamlit: streamlit run src/app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
