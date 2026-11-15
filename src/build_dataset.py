"""Arma las tablas de trabajo a partir de los datos crudos de data/.

Uso:
    python src/build_dataset.py

Genera en data/processed/:
    trips.parquet         un viaje por fila, 2022 a 2026, depurado y con el mismo formato todos los años
    stations.parquet      una estación por fila: ubicación, capacidad y distancia a ciclovías y transporte
    hours.parquet         una hora por fila: clima y calendario (día de semana, feriado)
    station_hour.parquet  una fila por estación y hora: salidas y llegadas
    daily_history.parquet un día por fila desde 2019: cantidad de viajes, para ver la evolución
"""

import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = DATA / "processed"

# Se usa desde 2022: en 2019 cambió el operador y el sistema, y 2020-2021 es pandemia.
TRIP_FILES = [
    "trips_2022.csv",
    "trips_2023.csv",
    "trips_2024_baddata.csv",
    "Trips_2025.csv",
    "trips_2026.csv",
]

# Años anteriores, que solo se usan para mostrar la evolución del sistema: en 2019 cambió el
# operador, en 2020 fue la pandemia y en 2021 se empezó a cobrar.
HISTORY_FILES = ["trips_2019.csv", "trips_2020.csv", "trips_2021.csv"]

# Límite de los datos: se usa todo lo anterior a octubre de 2026. Es el último mes completo que
# publicó el portal y fija un corte único para viajes, clima y calendario.
DATA_END = pd.Timestamp("2026-10-01")

# Un viaje de menos de un minuto es una bicicleta que se devolvió sin usar. Los archivos de todos
# los años ya vienen sin ellos salvo el de 2024, así que se aplica el mismo corte a todos.
MIN_DURATION_S = 60
# Más de un día es una bicicleta que no se devolvió, no un viaje.
MAX_DURATION_S = 24 * 3600

# Rectángulo que contiene a la Ciudad, para descartar coordenadas erróneas.
LON_RANGE = (-58.6, -58.3)
LAT_RANGE = (-34.75, -34.5)

# UTM zona 21 sur: proyección en metros adecuada para medir distancias en Buenos Aires.
METRIC_CRS = "EPSG:32721"

# Distancia máxima para aceptar que dos fuentes hablan de la misma estación.
SAME_STATION_M = 150
# Radio para medir cuánta ciclovía rodea a una estación.
BIKE_LANE_RADIUS_M = 300

WEATHER_COLUMNS = {
    "time": "hour",
    "temperature_2m (°C)": "temperature_c",
    "apparent_temperature (°C)": "apparent_temperature_c",
    "relative_humidity_2m (%)": "humidity_pct",
    "precipitation (mm)": "precipitation_mm",
    "rain (mm)": "rain_mm",
    "wind_speed_10m (km/h)": "wind_speed_kmh",
    "wind_gusts_10m (km/h)": "wind_gusts_kmh",
    "cloud_cover (%)": "cloud_cover_pct",
    "weather_code (wmo code)": "weather_code",
}


def to_id(series: pd.Series) -> pd.Series:
    """Convierte un identificador crudo a entero.

    :param series: identificadores como texto, con o sin sufijo ``BAEcobici`` o ``.0``.
    :returns: los identificadores como enteros que admiten faltantes.
    """
    cleaned = series.str.replace("BAEcobici", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce").round().astype("Int64")


def read_trip_file(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Lee un archivo anual de recorridos y lo lleva al formato común.

    :param path: archivo CSV de un año.
    :returns: los viajes depurados, las estaciones que aparecen en el archivo y un resumen de
        cuántos viajes se descartaron por cada motivo.
    """
    raw = pd.read_csv(path, dtype=str, engine="pyarrow", encoding="utf-8-sig")
    raw.columns = [column.strip().lower().replace("é", "e") for column in raw.columns]

    trips = pd.DataFrame(
        {
            "trip_id": to_id(raw["id_recorrido"]),
            "started_at": pd.to_datetime(raw["fecha_origen_recorrido"], errors="coerce"),
            "ended_at": pd.to_datetime(raw["fecha_destino_recorrido"], errors="coerce"),
            # La duración trae coma de miles ("2,814").
            "duration_s": pd.to_numeric(
                raw["duracion_recorrido"].str.replace(",", "", regex=False), errors="coerce"
            ),
            "origin_id": to_id(raw["id_estacion_origen"]),
            "destination_id": to_id(raw["id_estacion_destino"]),
            "user_id": to_id(raw["id_usuario"]),
            "bike_model": raw["modelo_bicicleta"],
            "gender": raw["genero"].where(raw["genero"].isin(["MALE", "FEMALE"]), "OTHER"),
        }
    )

    # Estaciones tal como figuran en el archivo, para reconstruir nombre y ubicación.
    stations = pd.concat(
        [
            pd.DataFrame(
                {
                    "station_id": trips[f"{side}_id"],
                    "name": raw[f"nombre_estacion_{source}"],
                    "lon": pd.to_numeric(raw[f"long_estacion_{source}"], errors="coerce"),
                    "lat": pd.to_numeric(raw[f"lat_estacion_{source}"], errors="coerce"),
                }
            )
            for side, source in (("origin", "origen"), ("destination", "destino"))
        ]
    )
    stations = stations[
        stations["station_id"].notna()
        & stations["lon"].between(*LON_RANGE)
        & stations["lat"].between(*LAT_RANGE)
    ]
    stations = stations.value_counts().rename("rows").reset_index()
    stations["year"] = int(trips["started_at"].dt.year.mode()[0])

    total = len(trips)
    incomplete = trips[["trip_id", "started_at", "ended_at", "origin_id", "destination_id"]].isna().any(axis=1)
    too_short = ~incomplete & (trips["duration_s"] < MIN_DURATION_S)
    too_long = ~incomplete & (trips["duration_s"] > MAX_DURATION_S)
    trips = trips[~(incomplete | too_short | too_long)]
    duplicated = trips["trip_id"].duplicated()
    trips = trips[~duplicated]
    summary = {
        "archivo": path.name,
        "leídos": total,
        "incompletos": int(incomplete.sum()),
        "menos de 1 min": int(too_short.sum()),
        "más de 24 h": int(too_long.sum()),
        "duplicados": int(duplicated.sum()),
        "quedan": len(trips),
    }

    trips = trips.astype(
        {
            "trip_id": "int64",
            "duration_s": "int32",
            "origin_id": "int16",
            "destination_id": "int16",
            "bike_model": "category",
            "gender": "category",
        }
    )
    return trips, stations, summary


def load_capacity() -> pd.DataFrame:
    """Lee la ubicación y capacidad actual de las estaciones desde el feed del operador.

    :returns: una fila por estación vigente, con identificador, nombre, coordenadas, capacidad y zona.
    """
    with (DATA / "stations" / "station_information.json").open(encoding="utf-8") as file:
        feed = json.load(file)["data"]["stations"]
    return pd.DataFrame(
        {
            "station_id": [int(station["station_id"]) for station in feed],
            "feed_name": [station["name"] for station in feed],
            "feed_lon": [station["lon"] for station in feed],
            "feed_lat": [station["lat"] for station in feed],
            "feed_capacity": [station["capacity"] for station in feed],
            "zone": [(station.get("groups") or [None])[0] for station in feed],
        }
    )


def load_capacity_2019() -> pd.DataFrame:
    """Lee la capacidad de las estaciones en 2019, del dataset de CONICET.

    :returns: una fila por estación con número, coordenadas y capacidad.
    """
    sheet = pd.read_excel(DATA / "conicet" / "estaciones_2019.xlsx")
    table = pd.DataFrame(
        {
            "station_id": pd.to_numeric(sheet["Número de la estación"], errors="coerce"),
            "lon_2019": sheet["Longitud de la estación"],
            "lat_2019": sheet["Latitud de la estación"],
            "capacity_2019": sheet["Capacidad"],
        }
    )
    return table.dropna().astype({"station_id": "int64"})


def to_points(frame: pd.DataFrame, lon: str, lat: str) -> gpd.GeoSeries:
    """Convierte columnas de longitud y latitud en puntos medidos en metros.

    :param frame: tabla con las coordenadas.
    :param lon: nombre de la columna de longitud.
    :param lat: nombre de la columna de latitud.
    :returns: los puntos en la proyección métrica, con el mismo índice que la tabla.
    """
    points = gpd.points_from_xy(frame[lon], frame[lat], crs="EPSG:4326")
    return gpd.GeoSeries(points, index=frame.index).to_crs(METRIC_CRS)


def nearest_distance(points: gpd.GeoSeries, targets: gpd.GeoSeries) -> np.ndarray:
    """Calcula la distancia de cada punto al objetivo más cercano.

    :param points: puntos de partida, en la proyección métrica.
    :param targets: geometrías de destino, en la misma proyección.
    :returns: la distancia en metros, en el orden de ``points``.
    """
    united = targets.union_all()
    return points.distance(united).round(1).to_numpy()


def build_stations(seen: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Arma la tabla de estaciones con ubicación, capacidad y entorno.

    :param seen: estaciones tal como figuran en cada archivo anual de recorridos.
    :param trips: todos los viajes depurados.
    :returns: una fila por estación.
    """
    # De cada estación se toma el nombre y la ubicación más frecuentes del último año en que aparece.
    latest = seen.sort_values(["year", "rows"]).drop_duplicates("station_id", keep="last")
    stations = latest[["station_id", "name", "lon", "lat"]].astype({"station_id": "int64"})

    activity = pd.concat(
        [
            trips[["origin_id", "started_at"]].set_axis(["station_id", "at"], axis=1),
            trips[["destination_id", "ended_at"]].set_axis(["station_id", "at"], axis=1),
        ]
    )
    activity = activity.groupby("station_id")["at"].agg(first_trip="min", last_trip="max", movements="size")
    # Una estación que nunca trae coordenadas válidas no se puede ubicar ni cruzar: queda afuera.
    stations = stations.merge(activity.reset_index(), on="station_id", how="inner")

    # Capacidad: la del feed actual si la estación sigue vigente y está en el mismo lugar.
    stations = stations.merge(load_capacity(), on="station_id", how="left")
    has_feed = stations["feed_capacity"].notna()
    distance = pd.Series(np.nan, index=stations.index)
    distance[has_feed] = to_points(stations[has_feed], "lon", "lat").distance(
        to_points(stations[has_feed], "feed_lon", "feed_lat")
    )
    same_place = has_feed & (distance <= SAME_STATION_M)
    stations["capacity"] = stations["feed_capacity"].where(same_place)
    stations["capacity_source"] = np.where(same_place, "feed 2026", None)
    stations["is_active"] = same_place

    # Para las que ya no están en el feed, la de 2019 si coincide en número y lugar.
    stations = stations.merge(load_capacity_2019(), on="station_id", how="left")
    candidate = stations["capacity"].isna() & stations["capacity_2019"].notna()
    distance = pd.Series(np.nan, index=stations.index)
    distance[candidate] = to_points(stations[candidate], "lon", "lat").distance(
        to_points(stations[candidate], "lon_2019", "lat_2019")
    )
    from_2019 = candidate & (distance <= SAME_STATION_M)
    stations.loc[from_2019, "capacity"] = stations.loc[from_2019, "capacity_2019"]
    stations.loc[from_2019, "capacity_source"] = "conicet 2019"
    stations["capacity"] = stations["capacity"].astype("Int16")

    # Entorno: ciclovías y transporte masivo.
    points = to_points(stations, "lon", "lat")
    lanes = gpd.read_file(DATA / "road" / "ciclovias.geojson").to_crs(METRIC_CRS).geometry
    all_lanes = lanes.union_all()
    stations["bike_lane_distance_m"] = points.distance(all_lanes).round(1).to_numpy()
    stations["bike_lane_m_within_300m"] = (
        points.buffer(BIKE_LANE_RADIUS_M).intersection(all_lanes).length.round(0).to_numpy()
    )

    transit = DATA / "transit"
    subway = gpd.read_file(transit / "estaciones_de_subte.geojson").to_crs(METRIC_CRS).geometry
    stations["subway_distance_m"] = nearest_distance(points, subway)
    # El archivo de tren abarca todo el área metropolitana; las de la Ciudad son las que tienen comuna.
    # Se dejan todas: una estación de bicicletas del borde puede tener más cerca una del conurbano.
    train = gpd.read_file(transit / "estaciones_ferroviarias.geojson").to_crs(METRIC_CRS).geometry
    stations["train_distance_m"] = nearest_distance(points, train)
    metrobus = gpd.read_file(transit / "estaciones-de-metrobus.geojson").to_crs(METRIC_CRS).geometry
    stations["metrobus_distance_m"] = nearest_distance(points, metrobus)

    columns = [
        "station_id", "name", "lon", "lat", "zone", "capacity", "capacity_source", "is_active",
        "first_trip", "last_trip", "movements", "bike_lane_distance_m", "bike_lane_m_within_300m",
        "subway_distance_m", "train_distance_m", "metrobus_distance_m",
    ]
    return stations[columns].sort_values("station_id").reset_index(drop=True)


def build_hours(first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    """Arma la tabla de horas con clima y calendario.

    :param first: primera hora a incluir.
    :param last: última hora a incluir.
    :returns: una fila por hora, sin huecos.
    """
    weather = pd.read_csv(DATA / "weather" / "open_meteo_horario_2019_2026.csv", skiprows=3)
    weather = weather.rename(columns=WEATHER_COLUMNS)
    weather["hour"] = pd.to_datetime(weather["hour"])
    # Algunos viajes del último día terminan pasada la medianoche; se corta en el límite de los datos.
    last = min(last, DATA_END - pd.Timedelta(hours=1))
    hours = pd.DataFrame({"hour": pd.date_range(first, last, freq="h")}).merge(weather, on="hour", how="left")

    holidays = pd.read_csv(DATA / "holidays" / "feriados_2019_2026.csv", parse_dates=["fecha"])
    holidays = holidays.rename(columns={"fecha": "date", "tipo": "holiday_type"})[["date", "holiday_type"]]
    hours["date"] = hours["hour"].dt.normalize()
    hours = hours.merge(holidays, on="date", how="left")
    hours["is_holiday"] = hours["holiday_type"].notna()
    hours["day_of_week"] = hours["hour"].dt.day_of_week.astype("int8")  # 0 = lunes
    hours["hour_of_day"] = hours["hour"].dt.hour.astype("int8")
    hours["is_weekend"] = hours["day_of_week"] >= 5
    # Día laborable: lunes a viernes que no es feriado.
    hours["is_workday"] = ~hours["is_weekend"] & ~hours["is_holiday"]
    return hours


def build_station_hour(trips: pd.DataFrame, stations: pd.DataFrame, hours: pd.DataFrame) -> pd.DataFrame:
    """Cuenta salidas y llegadas por estación y hora.

    Incluye las horas sin movimiento, porque para predecir hace falta saber cuándo no pasó nada.
    Cada estación se completa solo entre su primer y su último día con viajes.

    :param trips: todos los viajes depurados.
    :param stations: tabla de estaciones.
    :param hours: tabla de horas, sin huecos.
    :returns: una fila por estación y hora.
    """
    station_ids = stations["station_id"].to_numpy()
    station_index = pd.Index(station_ids)
    hour_index = pd.DatetimeIndex(hours["hour"])

    def count(station: pd.Series, at: pd.Series) -> np.ndarray:
        matrix = np.zeros((len(station_ids), len(hour_index)), dtype=np.int16)
        rows = station_index.get_indexer(station)
        columns = hour_index.get_indexer(at.dt.floor("h"))
        valid = (rows >= 0) & (columns >= 0)
        np.add.at(matrix, (rows[valid], columns[valid]), 1)
        return matrix

    departures = count(trips["origin_id"], trips["started_at"])
    arrivals = count(trips["destination_id"], trips["ended_at"])

    first = hour_index.get_indexer(stations["first_trip"].dt.normalize())
    last = hour_index.get_indexer(stations["last_trip"].dt.normalize() + pd.Timedelta(hours=23))
    last = np.where(last < 0, len(hour_index) - 1, last)
    pieces = []
    for row, station_id in enumerate(station_ids):
        span = slice(first[row], last[row] + 1)
        pieces.append(
            pd.DataFrame(
                {
                    "station_id": np.int16(station_id),
                    "hour": hour_index[span],
                    "departures": departures[row, span],
                    "arrivals": arrivals[row, span],
                }
            )
        )
    return pd.concat(pieces, ignore_index=True)


def build_daily_history(trips: pd.DataFrame) -> pd.DataFrame:
    """Cuenta los viajes por día desde 2019, para mostrar la evolución del sistema.

    De los años anteriores a 2022 solo se leen la fecha y la duración, con el mismo corte de
    duración que el resto.

    :param trips: viajes depurados de 2022 en adelante.
    :returns: una fila por día con la cantidad de viajes y si fue día laborable.
    """
    counts = [trips["started_at"].dt.normalize().value_counts()]
    for name in HISTORY_FILES:
        raw = pd.read_csv(
            DATA / "trips" / name, usecols=["fecha_origen_recorrido", "duracion_recorrido"],
            dtype=str, engine="pyarrow",
        )
        duration = pd.to_numeric(raw["duracion_recorrido"].str.replace(",", "", regex=False), errors="coerce")
        started = pd.to_datetime(raw["fecha_origen_recorrido"], errors="coerce")
        counts.append(started[duration.between(MIN_DURATION_S, MAX_DURATION_S)].dt.normalize().value_counts())
    daily = pd.concat(counts).sort_index().rename("trips").rename_axis("date").reset_index()

    holidays = pd.read_csv(DATA / "holidays" / "feriados_2019_2026.csv", parse_dates=["fecha"])["fecha"]
    daily["is_workday"] = (daily["date"].dt.day_of_week < 5) & ~daily["date"].isin(holidays)
    return daily


def main() -> int:
    started = time.time()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    all_trips, all_seen, summaries = [], [], []
    for name in TRIP_FILES:
        trips, seen, summary = read_trip_file(DATA / "trips" / name)
        all_trips.append(trips)
        all_seen.append(seen)
        summaries.append(summary)
        print(summary, flush=True)
    trips = pd.concat(all_trips, ignore_index=True)
    duplicated = trips["trip_id"].duplicated()
    trips = trips[~duplicated & (trips["started_at"] < DATA_END)]
    trips = trips.sort_values("started_at").reset_index(drop=True)
    print(f"viajes: {len(trips):,} (duplicados entre archivos: {int(duplicated.sum())})")
    trips.to_parquet(OUTPUT / "trips.parquet", index=False)

    stations = build_stations(pd.concat(all_seen, ignore_index=True), trips)
    stations.to_parquet(OUTPUT / "stations.parquet", index=False)
    unplaced = ~trips["origin_id"].isin(stations["station_id"]) | ~trips["destination_id"].isin(stations["station_id"])
    print(f"viajes con una estación sin ubicación conocida: {int(unplaced.sum())}")
    print(
        f"estaciones: {len(stations)}, vigentes {int(stations['is_active'].sum())}, "
        f"con capacidad {int(stations['capacity'].notna().sum())} "
        f"({stations['capacity_source'].value_counts().to_dict()})"
    )

    hours = build_hours(trips["started_at"].min().floor("h"), trips["ended_at"].max().floor("h"))
    hours.to_parquet(OUTPUT / "hours.parquet", index=False)
    print(f"horas: {len(hours):,}, sin clima {int(hours['temperature_c'].isna().sum())}")

    station_hour = build_station_hour(trips, stations, hours)
    station_hour.to_parquet(OUTPUT / "station_hour.parquet", index=False)
    print(
        f"estación-hora: {len(station_hour):,} filas, salidas {int(station_hour['departures'].sum()):,}, "
        f"llegadas {int(station_hour['arrivals'].sum()):,}"
    )
    daily = build_daily_history(trips)
    daily.to_parquet(OUTPUT / "daily_history.parquet", index=False)
    print(f"historia diaria: {len(daily):,} días, de {daily['date'].min():%d/%m/%Y} a {daily['date'].max():%d/%m/%Y}")
    print(f"listo en {time.time() - started:.0f} s -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
