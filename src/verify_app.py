"""Comprueba que la aplicación en HTML predice lo mismo que forecast.py.

Uso:
    python src/build_app.py
    python src/verify_app.py              # casos variados: tipos de día, lluvia, temperatura, resguardo
    python src/verify_app.py --all-days   # además, cada día del selector de fecha con el escenario por defecto

Necesita Node.js. Extrae de reports/app.html el motor de predicción y los datos, los ejecuta con
Node sobre los mismos casos que se calculan en Python con predict_day y plan_day, y compara salidas
y llegadas por estación y hora, y el stock recomendado y la indicación de cada estación. También
revisa que los datos incrustados (clima, viajes reales, feriados) sean los de las tablas.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

import build_app
import forecast

# Diferencia máxima aceptada en salidas o llegadas de una estación en una hora, en viajes.
TOLERANCE = 1e-3

# Fecha, feriado, clima y resguardo. El clima es "observed" o (milímetros por hora, desde, hasta,
# grados respecto de lo normal), como el panel lateral de la aplicación.
CASES = [
    ("Jueves laborable, seco", "2026-10-01", False, (0.0, 7, 12, 0), 2),
    ("Sábado, seco", "2026-08-08", False, (0.0, 7, 12, 0), 2),
    ("Feriado (9 de julio), seco", "2026-07-09", True, (0.0, 7, 12, 0), 2),
    ("Martes con lluvia a la mañana", "2026-09-15", False, (1.5, 7, 12, 0), 2),
    ("Posterior a los datos, lluvia fuerte todo el día", "2026-11-18", False, (4.0, 0, 23, 0), 2),
    ("Viernes de diciembre, llovizna a la tarde y 8 °C más", "2026-12-18", False, (0.3, 14, 19, 8), 4),
    ("Clima registrado, día más lluvioso de julio", "2026-07-31", False, "observed", 2),
    ("Clima registrado de octubre, sin viajes publicados", "2026-10-15", False, "observed", 3),
    ("Domingo 10 °C más frío, sin resguardo", "2026-07-19", False, (0.0, 7, 12, -10), 0),
    ("Feriado desmarcado, lluvia de 16 a 21 h", "2026-08-17", False, (1.5, 16, 20, 0), 5),
    ("Feriado posterior a los datos, lluvia fuerte y 3 °C menos", "2026-11-10", True, (4.0, 7, 12, -3), 1),
    ("Clima registrado, fin de septiembre", "2026-09-29", False, "observed", 2),
    ("Laborable marcado como feriado, llovizna", "2026-09-02", True, (0.3, 6, 9, 2), 2),
]

# Lo mismo que hace el motor de la página, ejecutado con Node.
HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const [htmlPath, casesPath, jsonPath, binPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, "utf8");
function block(id) {
  const match = html.match(new RegExp('<script[^>]*id="' + id + '"[^>]*>([\\s\\S]*?)</script>'));
  if (!match) throw new Error("No está el bloque " + id);
  return match[1];
}
const data = JSON.parse(block("app-data"));
const context = vm.createContext({atob});
vm.runInContext(block("engine"), context);
const engine = context.createEngine(data);

const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const results = [];
const chunks = [];
const started = Date.now();
for (const item of cases) {
  const day = engine.parseDay(item.date);
  const weather = item.weather === "observed"
    ? engine.observedWeather(day)
    : engine.scenarioWeather(day, item.weather[0], item.weather[1], item.weather[2], item.weather[3]);
  if (weather === null) throw new Error("No hay clima registrado para " + item.date);
  const prediction = engine.predictDay(day, weather, item.holiday);
  const plan = engine.planDay(prediction, item.margin);
  chunks.push(Buffer.from(prediction.departures.buffer), Buffer.from(prediction.arrivals.buffer));
  const number = value => value === value ? value : null;
  results.push({
    station_id: plan.map(row => row.station_id), status: plan.map(row => row.status),
    target_stock: plan.map(row => number(row.target_stock)), bikes_needed: plan.map(row => row.bikes_needed),
    docks_needed: plan.map(row => row.docks_needed), trips: plan.map(row => row.trips),
  });
}
fs.writeFileSync(binPath, Buffer.concat(chunks));
fs.writeFileSync(jsonPath, JSON.stringify({results, milliseconds: (Date.now() - started) / cases.length}));
"""


def case_weather(resources: forecast.Resources, day: pd.Timestamp, weather) -> pd.DataFrame:
    """Arma el clima de un caso igual que build_weather de src/app.py.

    :param resources: recursos cargados.
    :param day: día del caso.
    :param weather: "observed" o (milímetros por hora, desde, hasta, grados respecto de lo normal).
    :returns: el clima hora por hora.
    """
    if weather == "observed":
        return forecast.observed_weather(resources, day)
    rain, start, end, shift = weather
    table = forecast.typical_weather(resources, day)
    if rain > 0:
        table.loc[table["hour_of_day"].between(start, end), "precipitation_mm"] = rain
    table["apparent_temperature_c"] += shift
    return table


def python_case(resources: forecast.Resources, case: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calcula un caso con forecast.py.

    :param resources: recursos cargados.
    :param case: fecha, feriado, clima y resguardo.
    :returns: la predicción ordenada por estación y hora, y el plan ordenado por estación.
    """
    day = pd.Timestamp(case["date"])
    prediction = forecast.predict_day(resources, day, case_weather(resources, day, case["weather"]), case["holiday"])
    plan = forecast.plan_day(prediction, resources.stations, case["margin"])
    return prediction.sort_values(["station_id", "hour_of_day"]), plan.sort_values("station_id")


def check_embedded(resources: forecast.Resources, data: dict) -> list[str]:
    """Revisa que el clima, los viajes reales y los feriados incrustados sean los de las tablas.

    :param resources: recursos cargados.
    :param data: datos de la página.
    :returns: los problemas encontrados.
    """
    problems = []
    for month in range(1, 13):
        expected = forecast.typical_weather(resources, pd.Timestamp(2026, month, 1)).sort_values("hour_of_day")
        for position, name in enumerate(data["weather"]["variables"]):
            if expected[name].tolist() != data["weather"]["typical"][month - 1][position]:
                problems.append(f"Clima típico distinto en el mes {month}, {name}")

    start = pd.Timestamp(data["weather"]["observed_start"])
    for day in pd.date_range(data["dates"]["min"], data["dates"]["max"]):
        expected = forecast.observed_weather(resources, day)
        index = (day - start).days
        embedded = data["weather"]["observed"][index] if index < len(data["weather"]["observed"]) else None
        if (expected is None) != (embedded is None):
            problems.append(f"Disponibilidad del clima registrado distinta el {day:%Y-%m-%d}")
        elif expected is not None and any(
            expected[name].tolist() != embedded[position] for position, name in enumerate(forecast.WEATHER)
        ):
            problems.append(f"Clima registrado distinto el {day:%Y-%m-%d}")

    station_hour = pd.read_parquet(forecast.PROCESSED / "station_hour.parquet", columns=["hour", "departures"],
                                   filters=[("hour", ">=", pd.Timestamp(data["dates"]["min"]))])
    actual_start = pd.Timestamp(data["actual"]["start"])
    for day, rows in station_hour.groupby(station_hour["hour"].dt.normalize()):
        # Igual que show_check de src/app.py.
        expected = rows.groupby(rows["hour"].dt.hour)["departures"].sum().reindex(range(24), fill_value=0).tolist()
        index = (day - actual_start).days
        if index >= len(data["actual"]["days"]) or data["actual"]["days"][index] != expected:
            problems.append(f"Viajes reales distintos el {day:%Y-%m-%d}")
    if len(data["actual"]["days"]) != station_hour["hour"].dt.normalize().nunique():
        problems.append("La cantidad de días con viajes reales no coincide")

    if data["holidays"] != build_app.holidays_payload():
        problems.append("Los feriados no coinciden")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara la aplicación en HTML con forecast.py.")
    parser.add_argument("--all-days", action="store_true", help="agrega cada día del selector con el escenario por defecto")
    arguments = parser.parse_args()

    node = shutil.which("node")
    if node is None:
        print("Hace falta Node.js para ejecutar el motor de la página (https://nodejs.org).")
        return 1
    if not build_app.OUTPUT.exists():
        print(f"No está {build_app.OUTPUT}; primero corré python src/build_app.py.")
        return 1

    html = build_app.OUTPUT.read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script[^>]*id="app-data"[^>]*>(.*?)</script>', html, re.S).group(1))
    resources = forecast.load_resources()

    cases = [dict(label=label, date=date, holiday=holiday, weather=weather, margin=margin)
             for label, date, holiday, weather, margin in CASES]
    if arguments.all_days:
        holidays = set(data["holidays"])
        for day in pd.date_range(data["dates"]["min"], data["dates"]["max"]):
            text = f"{day:%Y-%m-%d}"
            cases.append(dict(label=f"Día {text}", date=text, holiday=text in holidays, weather=(0.0, 7, 12, 0),
                              margin=forecast.SAFETY_MARGIN))

    started = time.time()
    expected = [python_case(resources, case) for case in cases]
    python_seconds = (time.time() - started) / len(cases)

    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / "harness.js").write_text(HARNESS, encoding="utf-8")
        (folder / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        subprocess.run([node, str(folder / "harness.js"), str(build_app.OUTPUT), str(folder / "cases.json"),
                        str(folder / "results.json"), str(folder / "results.bin")], check=True)
        output = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        values = np.fromfile(folder / "results.bin", dtype="<f8")

    rows = len(data["stations"]["id"]) * 24
    worst = 0.0
    failures = 0
    print(f"{'Caso':58} {'dif. máx. viajes':>16} {'estados':>9} {'stock':>9}")
    for position, (case, (prediction, plan), result) in enumerate(zip(cases, expected, output["results"])):
        block = values[position * 2 * rows:(position + 1) * 2 * rows]
        same_stations = prediction["station_id"].drop_duplicates().tolist() == result["station_id"]
        difference = max(np.abs(block[:rows] - prediction["departures"].to_numpy()).max(),
                         np.abs(block[rows:] - prediction["arrivals"].to_numpy()).max()) if same_stations else np.inf
        status = (plan["status"].to_numpy() == np.array(result["status"])).sum() if same_stations else 0
        target = np.array([np.nan if value is None else value for value in result["target_stock"]], dtype=float)
        stock = (np.isclose(plan["target_stock"].to_numpy(float), target, rtol=0, atol=0, equal_nan=True)
                 & (plan["bikes_needed"].to_numpy() == np.array(result["bikes_needed"]))
                 & (plan["docks_needed"].to_numpy() == np.array(result["docks_needed"]))).sum() if same_stations else 0
        ok = same_stations and difference < TOLERANCE and status == len(plan) and stock == len(plan)
        failures += not ok
        worst = max(worst, difference)
        if not arguments.all_days or position < len(CASES) or not ok:
            print(f"{case['label'][:58]:58} {difference:16.2e} {status:4}/{len(plan):<4} {stock:4}/{len(plan):<4}"
                  + ("" if ok else "  <- NO COINCIDE"))

    problems = check_embedded(resources, data)
    for problem in problems:
        print("Datos incrustados:", problem)
    print(f"\n{len(cases)} casos, {len(cases) - failures} coinciden. Diferencia máxima: {worst:.2e} viajes "
          f"(tolerancia {TOLERANCE:g}). Datos incrustados: {'bien' if not problems else f'{len(problems)} problemas'}.")
    print(f"Tiempo por caso: Python {python_seconds * 1000:.0f} ms, JavaScript {output['milliseconds']:.0f} ms.")
    return 0 if failures == 0 and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
