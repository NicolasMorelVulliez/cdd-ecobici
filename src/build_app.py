"""Arma la aplicación del plan de redistribución en un solo archivo HTML.

Uso:
    python src/build_app.py

Guarda reports/app.html: la misma aplicación que src/app.py, pero en un archivo que abre con doble
clic, sin Python, sin servidor y sin conexión. Necesita haber corrido antes build_dataset.py,
cluster_stations.py y train_demand.py.

La predicción no está precalculada: se exportan los árboles de los dos modelos y el navegador los
recorre para el día y el clima que se elijan, con la misma lógica de forecast.py. Para que el
resultado sea el mismo que en Python, los datos que entran al modelo se guardan en precisión simple
(la que usa predict_day) y los valores de las hojas en precisión doble. src/verify_app.py comprueba
que las dos implementaciones coincidan.

La plantilla está en src/app_template.html.
"""

import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

import basemap
import forecast
from build_report import long_date, styled
from train_demand import FEATURES, TEST_FROM

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
TEMPLATE = Path(__file__).resolve().parent / "app_template.html"
OUTPUT = REPORTS / "app.html"

# Rango del selector de fecha: desde el primer día que el modelo no vio hasta fin de año.
DATE_MIN = pd.Timestamp(TEST_FROM)
DATE_MAX = pd.Timestamp("2026-12-31")
DATE_DEFAULT = pd.Timestamp("2026-10-01")

# Variables de estación que entran al modelo, en el orden en que se guardan.
STATION_FEATURES = ["cluster", "capacity", "lon", "lat", "subway_distance_m", "bike_lane_m_within_300m"]


def encode(values: np.ndarray, dtype: str) -> str:
    """Convierte un arreglo numérico a texto base64, para incrustarlo sin perder precisión.

    :param values: arreglo a guardar.
    :param dtype: tipo con que se guarda (en orden de bytes little-endian, el de los navegadores).
    :returns: los bytes del arreglo en base64.
    """
    array = np.ascontiguousarray(values, dtype=np.dtype(dtype).newbyteorder("<"))
    return base64.b64encode(array.tobytes()).decode("ascii")


def model_payload(model) -> dict:
    """Exporta los árboles de un HistGradientBoostingRegressor.

    Cada nodo guarda la variable que mira (-1 en las hojas), el umbral o el valor de la hoja, hacia
    dónde van los faltantes y el hijo derecho. scikit-learn guarda los nodos en preorden, así que el
    hijo izquierdo es siempre el nodo siguiente y no hace falta guardarlo. Los hijos se numeran
    dentro de su árbol, así que entran en un byte.

    :param model: modelo entrenado con pérdida de Poisson.
    :returns: los arreglos del modelo en base64 y el valor inicial.
    """
    if type(model._loss).__name__ != "HalfPoissonLoss" or model.n_trees_per_iteration_ != 1:
        raise SystemExit("El modelo no es el esperado: hace falta pérdida de Poisson y un árbol por iteración.")
    trees = [predictors[0].nodes for predictors in model._predictors]
    if any(tree["is_categorical"].any() for tree in trees):
        raise SystemExit("El modelo tiene variables categóricas; la aplicación no las sabe evaluar.")
    if max(len(tree) for tree in trees) > 256:
        raise SystemExit("Hay árboles de más de 256 nodos; no entran los hijos en un byte.")
    for tree in trees:
        splits = np.flatnonzero(tree["is_leaf"] == 0)
        if (tree["left"][splits] != splits + 1).any():
            raise SystemExit("Los nodos no están en preorden: el hijo izquierdo no es el siguiente.")
    nodes = np.concatenate(trees)
    leaf = nodes["is_leaf"].astype(bool)
    offsets = np.cumsum([0] + [len(tree) for tree in trees])
    return {
        "baseline": float(model._baseline_prediction.ravel()[0]),
        "offsets": encode(offsets, "uint32"),
        "feature": encode(np.where(leaf, -1, nodes["feature_idx"]), "int8"),
        "missing_left": encode(nodes["missing_go_to_left"], "uint8"),
        "right": encode(np.where(leaf, 0, nodes["right"]), "uint8"),
        # En las hojas, el valor; en los cortes, el umbral. Los dos en precisión doble.
        "number": encode(np.where(leaf, nodes["value"], nodes["num_threshold"]), "float64"),
    }


def optional(value):
    """Convierte un faltante de pandas en None, para el JSON."""
    return None if pd.isna(value) else value


def stations_payload(stations: pd.DataFrame) -> dict:
    """Datos de las estaciones: los que se muestran y los que entran al modelo.

    :param stations: estaciones con uso habitual, ordenadas por número.
    :returns: columnas con los datos de cada estación.
    """
    features = stations[STATION_FEATURES].astype("float64").to_numpy()
    return {
        "id": stations["station_id"].astype(int).tolist(),
        "name": stations["name"].tolist(),
        "zone": [optional(value) for value in stations["zone"]],
        "cluster_name": [optional(value) for value in stations["cluster_name"]],
        "capacity": [None if pd.isna(value) else int(value) for value in stations["capacity"]],
        # Para dibujar alcanza con 5 decimales (1 m); el modelo usa los valores de "features".
        "lon": stations["lon"].round(5).tolist(),
        "lat": stations["lat"].round(5).tolist(),
        "features": encode(features, "float32"),
    }


def usual_payload(usual: pd.DataFrame, ids: list[int]) -> str:
    """Uso habitual por estación, tipo de día y hora.

    :param usual: tabla de usual_profile.parquet.
    :param ids: estaciones en el orden de la aplicación.
    :returns: un arreglo de estación × (no laborable, laborable) × (salidas, llegadas) × hora.
    """
    table = usual.set_index(["station_id", "is_workday", "hour_of_day"])[["usual_departures", "usual_arrivals"]]
    index = pd.MultiIndex.from_product([ids, [False, True], range(24)], names=table.index.names)
    table = table.reindex(index)
    if table.isna().any().any():
        raise SystemExit("Falta el uso habitual de alguna estación, tipo de día u hora.")
    values = table.to_numpy().reshape(len(ids), 2, 24, 2).transpose(0, 1, 3, 2)
    return encode(values, "float32")


def recent_payload(recent: pd.DataFrame, ids: list[int], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Nivel reciente de cada estación para cada día con viajes, desde ``start``.

    predict_day usa el último valor conocido hasta la fecha; acá se calcula ese valor día por día,
    y para una fecha posterior a ``end`` la aplicación usa el del último día.

    :param recent: tabla de nivel reciente de forecast.load_resources.
    :param ids: estaciones en el orden de la aplicación.
    :param start: primer día.
    :param end: último día con viajes.
    :returns: el primer día, la cantidad de días y los valores (estación × día, NaN si no hay).
    """
    table = recent.pivot(index="date", columns="station_id", values="recent_daily_departures")
    table = table.reindex(pd.date_range(table.index.min(), end)).ffill()
    table = table.loc[start:end].reindex(columns=ids)
    return {"start": f"{start:%Y-%m-%d}", "days": len(table), "values": encode(table.to_numpy().T, "float32")}


def weather_payload(resources: forecast.Resources, start: pd.Timestamp) -> dict:
    """Clima típico de cada mes y clima registrado de cada día desde ``start``.

    Se guarda en precisión doble porque la aplicación todavía le suma la lluvia y la temperatura
    del escenario antes de pasarlo al modelo.

    :param resources: recursos cargados.
    :param start: primer día del clima registrado.
    :returns: el clima típico por mes y el registrado por día (None si el día no está completo).
    """
    variables = forecast.WEATHER[1:]
    typical = []
    for month in range(1, 13):
        weather = forecast.typical_weather(resources, pd.Timestamp(2026, month, 1)).sort_values("hour_of_day")
        if len(weather) != 24 or (weather["precipitation_mm"] != 0).any():
            raise SystemExit(f"El clima típico del mes {month} no tiene las 24 horas.")
        typical.append([weather[name].astype(float).tolist() for name in variables])

    end = resources.hours["date"].max()
    observed = []
    for day in pd.date_range(start, end):
        weather = forecast.observed_weather(resources, day)
        observed.append(None if weather is None else [
            weather.sort_values("hour_of_day")[name].astype(float).tolist() for name in forecast.WEATHER
        ])
    return {"variables": variables, "typical": typical, "observed_start": f"{start:%Y-%m-%d}", "observed": observed}


def actual_payload(start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Viajes reales por hora de todo el sistema, para comparar con la predicción.

    :param start: primer día.
    :param end: último día con viajes.
    :returns: el primer día y 24 valores por día.
    """
    filters = [("hour", ">=", start), ("hour", "<", end + pd.Timedelta(days=1))]
    station_hour = pd.read_parquet(forecast.PROCESSED / "station_hour.parquet", columns=["hour", "departures"],
                                   filters=filters)
    hourly = station_hour.groupby("hour")["departures"].sum()
    hourly = hourly.reindex(pd.date_range(start, end + pd.Timedelta(hours=23), freq="h"), fill_value=0)
    return {"start": f"{start:%Y-%m-%d}", "days": hourly.to_numpy().astype(int).reshape(-1, 24).tolist()}


def holidays_payload() -> dict:
    """Feriados del año de la aplicación, con su nombre."""
    table = pd.read_csv(DATA / "holidays" / "feriados_2019_2026.csv", parse_dates=["fecha"])
    table = table[table["fecha"].dt.year == DATE_MAX.year]
    # Si un día figura dos veces queda el último nombre, como en src/app.py.
    return {f"{day:%Y-%m-%d}": name for day, name in zip(table["fecha"], table["nombre"])}


def lanes_payload() -> list[list[int]]:
    """Red de ciclovías, un tramo por lista.

    Las coordenadas van en cienmilésimas de grado (unos 1 m, el mismo redondeo que el reporte) y,
    salvo el primer punto de cada tramo, como diferencia con el anterior: así ocupan la mitad.

    :returns: por tramo, longitud y latitud del primer punto y después las diferencias, alternadas.
    """
    with (DATA / "road" / "ciclovias.geojson").open(encoding="utf-8") as file:
        features = json.load(file)["features"]
    segments = []
    for feature in features:
        points = np.rint(np.array(feature["geometry"]["coordinates"]) * 1e5).astype(int)
        steps = np.vstack([points[:1], np.diff(points, axis=0)])
        segments.append(steps.ravel().tolist())
    return segments


def layouts() -> dict:
    """Diseños de los gráficos, con el mismo estilo que el reporte general."""
    legend = dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=14))
    return {
        "map": styled(go.Figure(), height=760, margin=dict(l=0, r=0, t=40, b=0), hovermode="closest",
                      legend=dict(legend, title_text="", traceorder="reversed", itemsizing="constant"),
                      **basemap.layout())["layout"],
        "station": styled(go.Figure(), height=480, barmode="relative", bargap=0.25, hovermode="x unified",
                          xaxis=dict(title="Hora", dtick=1), yaxis_title="Bicicletas", legend=legend)["layout"],
        "check": styled(go.Figure(), height=460, hovermode="x unified", xaxis=dict(title="Hora", dtick=2),
                        yaxis=dict(title="Viajes por hora en todo el sistema", rangemode="tozero"),
                        legend=legend)["layout"],
    }


def build_payload() -> dict:
    """Junta todo lo que necesita la aplicación.

    :returns: los datos y los modelos, listos para pasar a JSON.
    """
    resources = forecast.load_resources()
    if resources.features != FEATURES:
        raise SystemExit("Las variables del modelo no son las de train_demand.FEATURES.")

    # Las mismas estaciones que predict_day: las que tienen uso habitual.
    stations = resources.stations[resources.stations["station_id"].isin(resources.usual["station_id"])]
    stations = stations.sort_values("station_id").reset_index(drop=True)
    ids = stations["station_id"].astype(int).tolist()
    trips_end = resources.recent["date"].max()

    return {
        "features": FEATURES,
        "station_features": STATION_FEATURES,
        "start_hour": forecast.START_HOUR,
        "safety_margin": forecast.SAFETY_MARGIN,
        "dates": {"min": f"{DATE_MIN:%Y-%m-%d}", "max": f"{DATE_MAX:%Y-%m-%d}",
                  "default": f"{DATE_DEFAULT:%Y-%m-%d}", "trips_end": f"{trips_end:%Y-%m-%d}"},
        "stations": stations_payload(stations),
        "usual": usual_payload(resources.usual, ids),
        "recent": recent_payload(resources.recent, ids, DATE_MIN, trips_end),
        "weather": weather_payload(resources, DATE_MIN),
        "actual": actual_payload(DATE_MIN, trips_end),
        "holidays": holidays_payload(),
        "lanes": lanes_payload(),
        "layouts": layouts(),
        "models": {target: model_payload(resources.models[target]) for target in forecast.TARGETS},
    }


def main() -> int:
    started = time.time()
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    # «</» se escapa para que ningún texto pueda cerrar antes de tiempo el bloque <script> de los datos.
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    values = {
        "data_json": data_json,
        "trips_end": long_date(payload["dates"]["trips_end"]),
        "generated": long_date(datetime.now()),
        "attribution": basemap.ATTRIBUTION,
        # El mapa se acerca igual que en el reporte: con los botones, o con la rueda después de un clic.
        "map_config_json": json.dumps(basemap.CONFIG),
        "map_zoom_js": basemap.zoom_script(),
        "plotly_js": get_plotlyjs(),
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    missing = [key for key in values if "{{" + key + "}}" not in html]
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", value)
    # Se revisa solo la parte propia: el código de Plotly y los datos pueden contener llaves dobles.
    own = html.replace(values["plotly_js"], "").replace(values["data_json"], "")
    if "{{" in own or missing:
        start = own.find("{{")
        raise SystemExit(f"Plantilla y datos no coinciden. Sin usar: {missing}. Sin completar: {own[start:start + 40]!r}")

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Aplicación en {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.1f} MB, {time.time() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
