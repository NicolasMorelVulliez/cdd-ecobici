"""Predicción de un día completo y proyección del stock de cada estación.

Lo usa la aplicación (src/app.py). Necesita las tablas de data/processed/ y los modelos de models/,
que generan build_dataset.py, cluster_stations.py y train_demand.py.
"""

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"

TARGETS = ["departures", "arrivals"]
WEATHER = ["precipitation_mm", "apparent_temperature_c", "wind_speed_kmh", "cloud_cover_pct"]

# Hora en que empieza la operación del día: entre la medianoche y las 5 casi no hay viajes, y es
# cuando los camiones pueden dejar cada estación como conviene.
START_HOUR = 5
# Resguardo por defecto: el modelo se equivoca en unas 2 bicicletas en el balance de una mañana.
SAFETY_MARGIN = 2


@dataclass
class Resources:
    """Todo lo que hace falta para predecir, cargado una sola vez."""

    stations: pd.DataFrame
    usual: pd.DataFrame
    hours: pd.DataFrame
    recent: pd.DataFrame
    holidays: set
    models: dict
    features: list


def load_resources() -> Resources:
    """Carga tablas y modelos.

    :returns: los recursos listos para predecir.
    """
    stations = pd.read_parquet(PROCESSED / "stations.parquet")
    clusters = pd.read_parquet(PROCESSED / "station_clusters.parquet")[["station_id", "cluster", "cluster_name"]]
    stations = stations.merge(clusters, on="station_id", how="left")
    hours = pd.read_parquet(PROCESSED / "hours.parquet")

    # Nivel reciente de cada estación: promedio de salidas diarias de las cuatro semanas anteriores.
    station_hour = pd.read_parquet(PROCESSED / "station_hour.parquet", columns=["station_id", "hour", "departures"])
    daily = station_hour.groupby(["station_id", station_hour["hour"].dt.normalize().rename("date")])["departures"].sum()
    recent = daily.groupby(level="station_id").transform(lambda values: values.shift(1).rolling(28, min_periods=7).mean())
    recent = recent.rename("recent_daily_departures").reset_index().dropna()

    # Los modelos los genera train_demand.py en esta misma máquina; no se cargan archivos ajenos.
    bundles = {target: joblib.load(MODELS / f"demand_{target}.joblib") for target in TARGETS}
    return Resources(
        stations=stations,
        usual=pd.read_parquet(PROCESSED / "usual_profile.parquet"),
        hours=hours,
        recent=recent,
        holidays=set(hours.loc[hours["is_holiday"], "date"]),
        models={target: bundle["model"] for target, bundle in bundles.items()},
        features=bundles["departures"]["features"],
    )


def typical_weather(resources: Resources, date: pd.Timestamp) -> pd.DataFrame:
    """Clima típico de un día seco de ese mes, hora por hora.

    :param resources: recursos cargados.
    :param date: día a predecir.
    :returns: 24 filas con las variables de clima, sin lluvia.
    """
    hours = resources.hours
    same_month = hours[(hours["hour"].dt.month == date.month) & (hours["precipitation_mm"] == 0)]
    weather = same_month.groupby("hour_of_day")[WEATHER].median().reset_index()
    weather["precipitation_mm"] = 0.0
    return weather


def observed_weather(resources: Resources, date: pd.Timestamp) -> pd.DataFrame | None:
    """Clima registrado ese día, si está dentro de los datos.

    :param resources: recursos cargados.
    :param date: día a consultar.
    :returns: 24 filas con las variables de clima, o None si el día no tiene datos.
    """
    day = resources.hours[resources.hours["date"] == date]
    return day[["hour_of_day"] + WEATHER].reset_index(drop=True) if len(day) == 24 else None


def predict_day(resources: Resources, date: pd.Timestamp, weather: pd.DataFrame, is_holiday: bool) -> pd.DataFrame:
    """Predice salidas y llegadas de cada estación para las 24 horas de un día.

    :param resources: recursos cargados.
    :param date: día a predecir.
    :param weather: clima hora por hora (24 filas con ``hour_of_day`` y las variables de clima).
    :param is_holiday: si el día es feriado.
    :returns: una fila por estación y hora con ``departures`` y ``arrivals`` predichas.
    """
    weather = weather.sort_values("hour_of_day").copy()
    weather["precipitation_prev_3h"] = weather["precipitation_mm"].shift(1).rolling(3, min_periods=1).sum().fillna(0)
    is_workday = date.day_of_week < 5 and not is_holiday

    # Para un día posterior a los datos se usa el último nivel reciente conocido de cada estación.
    recent = resources.recent[resources.recent["date"] <= date]
    recent = recent.sort_values("date").drop_duplicates("station_id", keep="last")[["station_id", "recent_daily_departures"]]

    usual = resources.usual[resources.usual["is_workday"] == is_workday].drop(columns="is_workday")
    table = resources.stations.merge(usual, on="station_id").merge(recent, on="station_id", how="left")
    table = table.merge(weather, on="hour_of_day")
    table["day_of_week"] = date.day_of_week
    table["month"] = date.month
    table["is_workday"] = is_workday
    table["is_holiday"] = is_holiday

    features = table[resources.features].to_numpy(dtype="float32")
    for target in TARGETS:
        table[target] = resources.models[target].predict(features)
    return table[["station_id", "hour_of_day", "departures", "arrivals", "usual_departures", "usual_arrivals"]]


def plan_day(prediction: pd.DataFrame, stations: pd.DataFrame, margin: int = SAFETY_MARGIN) -> pd.DataFrame:
    """Calcula con cuántas bicicletas conviene que arranque el día cada estación.

    No se sabe cuántas bicicletas hay en cada estación, así que en vez de adivinar el stock y ver
    qué pasa, se calcula lo que la estación necesita. Se acumulan las llegadas menos las salidas
    previstas desde el inicio de la operación: el punto más bajo de esa cuenta dice cuántas
    bicicletas tiene que haber al arrancar para no quedarse sin ninguna, y el más alto, cuántos
    anclajes libres hacen falta para que siempre se pueda devolver.

    Si las dos necesidades juntas no entran en la capacidad, no hay stock inicial que alcance y la
    estación necesita una visita durante el día.

    :param prediction: salida de ``predict_day``.
    :param stations: tabla de estaciones, con la capacidad.
    :param margin: bicicletas (y anclajes) de resguardo que se suman a cada necesidad.
    :returns: una fila por estación con el stock inicial recomendado y su diagnóstico.
    """
    day = prediction[prediction["hour_of_day"] >= START_HOUR]
    net = (day["arrivals"] - day["departures"]).rename("net")
    path = pd.concat([day[["station_id", "hour_of_day"]], net], axis=1).pivot(
        index="station_id", columns="hour_of_day", values="net"
    ).cumsum(axis=1)

    columns = ["name", "zone", "cluster_name", "capacity", "lon", "lat"]
    result = stations.set_index("station_id").loc[path.index, columns].copy()
    capacity = result["capacity"].astype(float)
    result["trips"] = prediction.groupby("station_id")["departures"].sum()
    result["net_day"] = path.iloc[:, -1]
    result["bikes_needed"] = np.ceil((-path.min(axis=1)).clip(lower=0)) + margin
    result["docks_needed"] = np.ceil(path.max(axis=1).clip(lower=0)) + margin
    result["lowest_hour"] = path.idxmin(axis=1)
    result["highest_hour"] = path.idxmax(axis=1)

    fits = result["bikes_needed"] + result["docks_needed"] <= capacity
    # Dentro del rango que sirve, se recomienda el punto medio: deja el mismo resguardo de los dos lados.
    midpoint = (result["bikes_needed"] + capacity - result["docks_needed"]) / 2
    result["target_stock"] = np.where(fits, midpoint.round(), np.minimum(result["bikes_needed"], capacity))
    result["target_share"] = result["target_stock"] / capacity
    result["status"] = np.select(
        [capacity.isna(), ~fits, result["target_share"] >= 0.6, result["target_share"] <= 0.4],
        ["Sin capacidad conocida", "Necesita visita durante el día", "Arrancar cargada", "Arrancar con lugar"],
        "Arrancar a media carga",
    )
    return result.reset_index()


def stock_path(prediction: pd.DataFrame, station_id: int, initial_stock: float) -> pd.DataFrame:
    """Devuelve la proyección hora por hora de una estación.

    :param prediction: salida de ``predict_day``.
    :param station_id: estación a detallar.
    :param initial_stock: bicicletas con las que arranca el día.
    :returns: 24 filas con salidas, llegadas y stock proyectado al final de cada hora.
    """
    station = prediction[(prediction["station_id"] == station_id) & (prediction["hour_of_day"] >= START_HOUR)]
    station = station.sort_values("hour_of_day").copy()
    station["stock"] = initial_stock + (station["arrivals"] - station["departures"]).cumsum()
    return station
