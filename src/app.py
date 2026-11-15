"""Aplicación: con cuántas bicicletas conviene que arranque mañana cada estación de Ecobici.

Uso:
    streamlit run src/app.py

Funciona sin conexión. Necesita haber corrido antes build_dataset.py, cluster_stations.py y
train_demand.py.
"""

import json
from datetime import date as Date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import basemap
import forecast

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Lluvia por hora de cada escenario, en milímetros.
RAIN_SCENARIOS = {"Sin lluvia": 0.0, "Llovizna": 0.3, "Lluvia": 1.5, "Lluvia fuerte": 4.0}

STATUS_COLORS = {
    "Arrancar cargada": "#c0392b",
    "Arrancar con lugar": "#2471a3",
    "Necesita visita durante el día": "#8e44ad",
    "Arrancar a media carga": "#aab7b8",
    "Sin capacidad conocida": "#e5e8e8",
}
DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@st.cache_resource(show_spinner="Cargando modelos y datos…")
def load_resources() -> forecast.Resources:
    """Carga tablas y modelos una sola vez por sesión."""
    return forecast.load_resources()


@st.cache_data
def load_holidays() -> dict:
    """Lee los feriados.

    :returns: un diccionario de fecha a nombre del feriado.
    """
    table = pd.read_csv(DATA / "holidays" / "feriados_2019_2026.csv", parse_dates=["fecha"])
    return dict(zip(table["fecha"], table["nombre"]))


@st.cache_data
def load_bike_lanes() -> tuple[list, list]:
    """Lee la red de ciclovías como una sola línea quebrada, para dibujarla de fondo.

    :returns: longitudes y latitudes, con None entre un tramo y el siguiente.
    """
    with (DATA / "road" / "ciclovias.geojson").open(encoding="utf-8") as file:
        features = json.load(file)["features"]
    lons, lats = [], []
    for feature in features:
        for lon, lat in feature["geometry"]["coordinates"]:
            lons.append(lon)
            lats.append(lat)
        lons.append(None)
        lats.append(None)
    return lons, lats


@st.cache_data
def load_actual(day: pd.Timestamp) -> pd.DataFrame:
    """Lee los viajes reales de un día, si está dentro de los datos.

    :param day: día a consultar.
    :returns: salidas y llegadas reales por estación y hora; vacío si no hay datos.
    """
    filters = [("hour", ">=", day), ("hour", "<", day + pd.Timedelta(days=1))]
    return pd.read_parquet(forecast.PROCESSED / "station_hour.parquet", filters=filters)


def build_weather(resources: forecast.Resources, day: pd.Timestamp) -> tuple[pd.DataFrame, str]:
    """Arma el clima del día a partir de lo que se elige en el panel lateral.

    :param resources: recursos cargados.
    :param day: día a planificar.
    :returns: el clima hora por hora y una descripción corta.
    """
    observed = forecast.observed_weather(resources, day)
    options = ["Escenario"] + (["Clima registrado ese día"] if observed is not None else [])
    source = st.sidebar.radio("Clima", options, help="Para un día pasado se puede usar el clima que hubo.")
    if source != "Escenario":
        rain = observed["precipitation_mm"].sum()
        return observed, f"clima registrado, {rain:.1f} mm de lluvia".replace(".", ",")

    weather = forecast.typical_weather(resources, day)
    scenario = st.sidebar.selectbox("Lluvia", list(RAIN_SCENARIOS))
    description = scenario.lower()
    if RAIN_SCENARIOS[scenario] > 0:
        start, end = st.sidebar.slider("Horas con lluvia", 0, 23, (7, 12))
        weather.loc[weather["hour_of_day"].between(start, end), "precipitation_mm"] = RAIN_SCENARIOS[scenario]
        description += f" de {start} a {end + 1} h"
    shift = st.sidebar.slider("Temperatura respecto de lo normal del mes (°C)", -10, 10, 0)
    weather["apparent_temperature_c"] += shift
    if shift:
        description += f", {abs(shift)} °C {'más' if shift > 0 else 'menos'} que lo normal"
    return weather, description


def show_map(plan: pd.DataFrame) -> None:
    """Dibuja las estaciones sobre el mapa de la Ciudad, coloreadas por cómo conviene dejarlas."""
    with_lanes = st.checkbox("Mostrar ciclovías", value=True)
    shown = plan.dropna(subset=["lon", "lat"]).copy()
    shown["Dejar con"] = shown["target_stock"].map(lambda value: "—" if pd.isna(value) else f"{value:.0f} bicicletas")
    figure = px.scatter(
        shown, x="lon", y="lat", color="status", size="trips", size_max=15,
        color_discrete_map=STATUS_COLORS, category_orders={"status": list(STATUS_COLORS)},
        hover_name="name",
        hover_data={"Dejar con": True, "capacity": True, "cluster_name": True, "trips": ":.0f",
                    "status": False, "lat": False, "lon": False},
        labels={"status": "Cómo dejarla", "capacity": "Capacidad", "cluster_name": "Tipo", "trips": "Viajes previstos"},
        height=760,
    )
    figure.update_traces(marker=dict(line=dict(color="white", width=1), opacity=0.92))
    # Las estaciones que no piden nada se dibujan primero, para que no tapen a las que hay que preparar.
    figure.data = figure.data[::-1]
    if with_lanes:
        lons, lats = load_bike_lanes()
        figure.add_scatter(x=lons, y=lats, mode="lines", line=dict(color="#1baf7a", width=1), opacity=0.6,
                           name="Ciclovías", hoverinfo="skip")
        # Las ciclovías van al fondo para que no tapen las estaciones.
        figure.data = (figure.data[-1],) + figure.data[:-1]
    figure.update_layout(
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text="", font=dict(size=14),
                    traceorder="reversed", itemsizing="constant"),
        **basemap.layout(),
    )
    # Acá la rueda acerca siempre: el mapa es el centro de la pestaña y Streamlit no deja agregarle
    # el código que la activa con un clic.
    st.plotly_chart(figure, width="stretch", config=basemap.CONFIG)
    st.caption(f"El tamaño de cada punto es la cantidad de viajes previstos. {basemap.ATTRIBUTION}.")


def show_plan(plan: pd.DataFrame, day: pd.Timestamp) -> None:
    """Muestra la lista de estaciones con el stock con que conviene dejarlas."""
    order = {status: position for position, status in enumerate(STATUS_COLORS)}
    table = plan.assign(order=plan["status"].map(order)).sort_values(["order", "trips"], ascending=[True, False])
    table = table.rename(
        columns={
            "name": "Estación", "zone": "Zona", "cluster_name": "Tipo", "capacity": "Capacidad",
            "target_stock": "Dejar con", "bikes_needed": "Bicicletas mínimas",
            "docks_needed": "Anclajes libres mínimos", "trips": "Viajes previstos", "status": "Indicación",
        }
    )
    columns = ["Estación", "Zona", "Tipo", "Indicación", "Capacidad", "Dejar con", "Bicicletas mínimas",
               "Anclajes libres mínimos", "Viajes previstos"]
    only_action = st.checkbox("Solo las que necesitan preparación", value=True)
    if only_action:
        table = table[table["Indicación"].isin(list(STATUS_COLORS)[:3])]
    st.dataframe(table[columns], hide_index=True, width="stretch", height=520,
                 column_config={"Viajes previstos": st.column_config.NumberColumn(format="%.0f")})
    st.download_button(
        "Descargar el plan (CSV)", table[columns].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"plan_ecobici_{day:%Y-%m-%d}.csv", mime="text/csv",
    )

    st.subheader("Por zona")
    zones = plan.dropna(subset=["zone", "capacity"]).groupby("zone").agg(
        Estaciones=("name", "size"), Capacidad=("capacity", "sum"), Objetivo=("target_stock", "sum"),
        Viajes=("trips", "sum"),
    )
    zones["Carga objetivo (%)"] = (100 * zones["Objetivo"] / zones["Capacidad"]).round(0)
    zones = zones.rename(columns={"Objetivo": "Bicicletas a dejar", "Viajes": "Viajes previstos"})
    st.dataframe(zones.sort_values("Viajes previstos", ascending=False).rename_axis("Zona"), width="stretch",
                 column_config={"Viajes previstos": st.column_config.NumberColumn(format="%.0f")})


def show_station(plan: pd.DataFrame, prediction: pd.DataFrame) -> None:
    """Muestra el detalle hora por hora de una estación."""
    with_capacity = plan.dropna(subset=["capacity"]).sort_values("trips", ascending=False)
    names = dict(zip(with_capacity["station_id"], with_capacity["name"]))
    station_id = st.selectbox("Estación", list(names), format_func=names.get)
    station = with_capacity.set_index("station_id").loc[station_id]
    path = forecast.stock_path(prediction, station_id, station["target_stock"])

    left, middle, right = st.columns(3)
    left.metric("Tipo de estación", station["cluster_name"] if pd.notna(station["cluster_name"]) else "Sin clasificar")
    middle.metric("Capacidad", f"{station['capacity']:.0f} anclajes")
    right.metric("Dejar con", f"{station['target_stock']:.0f} bicicletas", station["status"], delta_color="off")

    figure = go.Figure()
    figure.add_bar(x=path["hour_of_day"], y=path["arrivals"], name="Llegadas previstas", marker_color="#2471a3")
    figure.add_bar(x=path["hour_of_day"], y=-path["departures"], name="Salidas previstas", marker_color="#c0392b")
    figure.add_scatter(x=path["hour_of_day"], y=path["stock"], name="Bicicletas en la estación",
                       mode="lines+markers", line=dict(color="black", width=3))
    figure.add_hline(y=float(station["capacity"]), line_dash="dash", annotation_text="Capacidad")
    figure.add_hline(y=0, line_color="gray")
    figure.update_layout(barmode="relative", template="plotly_white", height=480, font=dict(size=16),
                         xaxis_title="Hora", yaxis_title="Bicicletas", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(figure, width="stretch")
    st.caption("La línea negra muestra cuántas bicicletas habría si la estación arranca con el stock recomendado "
               "y nadie la repone durante el día.")


def show_check(prediction: pd.DataFrame, day: pd.Timestamp) -> None:
    """Compara la predicción con lo que pasó, cuando el día está dentro de los datos."""
    actual = load_actual(day)
    if actual.empty:
        st.info("Para este día no hay viajes publicados, así que no hay con qué comparar. "
                "Elegí un día anterior para ver cómo le fue al modelo.")
        return
    real = actual.groupby(actual["hour"].dt.hour)["departures"].sum()
    predicted = prediction.groupby("hour_of_day")["departures"].sum()
    usual = prediction.groupby("hour_of_day")["usual_departures"].sum()
    left, middle, right = st.columns(3)
    left.metric("Viajes reales", f"{real.sum():,.0f}".replace(",", "."))
    middle.metric("Viajes previstos por el modelo", f"{predicted.sum():,.0f}".replace(",", "."),
                  f"{100 * (predicted.sum() / real.sum() - 1):+.0f}% respecto de lo real", delta_color="off")
    right.metric("Lo habitual para ese tipo de día", f"{usual.sum():,.0f}".replace(",", "."),
                 f"{100 * (usual.sum() / real.sum() - 1):+.0f}% respecto de lo real", delta_color="off")
    figure = go.Figure()
    figure.add_scatter(x=real.index, y=real.values, name="Real", line=dict(color="black", width=4))
    figure.add_scatter(x=predicted.index, y=predicted.values, name="Modelo", line=dict(color="#c0392b", width=3))
    figure.add_scatter(x=usual.index, y=usual.values, name="Lo habitual", line=dict(color="#aab7b8", width=3, dash="dash"))
    figure.update_layout(template="plotly_white", height=460, font=dict(size=16), xaxis_title="Hora",
                         yaxis_title="Viajes por hora en todo el sistema", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(figure, width="stretch")
    st.caption("Para una comparación justa, elegí «Clima registrado ese día» en el panel lateral.")


def main() -> None:
    st.set_page_config(page_title="Ecobici: plan de redistribución", layout="wide")
    resources = load_resources()
    holidays = load_holidays()

    st.sidebar.header("Día a planificar")
    chosen = st.sidebar.date_input("Fecha", Date(2026, 10, 1), min_value=Date(2025, 1, 1),
                                   max_value=Date(2026, 12, 31), format="DD/MM/YYYY")
    day = pd.Timestamp(chosen)
    is_holiday = st.sidebar.checkbox("Es feriado", value=day in holidays, help=holidays.get(day))
    weather, description = build_weather(resources, day)
    margin = st.sidebar.slider("Bicicletas de resguardo por estación", 0, 5, forecast.SAFETY_MARGIN,
                               help="El modelo se equivoca en unas 2 bicicletas en el balance de una mañana.")

    prediction = forecast.predict_day(resources, day, weather, is_holiday)
    plan = forecast.plan_day(prediction, resources.stations, margin)
    dry = forecast.predict_day(resources, day, forecast.typical_weather(resources, day), is_holiday)

    kind = "feriado" if is_holiday else DAY_NAMES[day.day_of_week]
    st.title("¿Cómo dejar cada estación para mañana?")
    st.markdown(f"**{day:%d/%m/%Y}** ({kind}), {description}.")

    trips, dry_trips = prediction["departures"].sum(), dry["departures"].sum()
    counts = plan["status"].value_counts()
    first, second, third, fourth = st.columns(4)
    first.metric("Viajes previstos", f"{trips:,.0f}".replace(",", "."),
                 f"{100 * (trips / dry_trips - 1):+.0f}% respecto de un día seco" if abs(trips - dry_trips) > 1 else None)
    second.metric("Estaciones a dejar cargadas", int(counts.get("Arrancar cargada", 0)))
    third.metric("Estaciones a dejar con lugar", int(counts.get("Arrancar con lugar", 0)))
    fourth.metric("Necesitan visita durante el día", int(counts.get("Necesita visita durante el día", 0)))

    map_tab, plan_tab, station_tab, check_tab = st.tabs(
        ["Mapa", "Plan de redistribución", "Detalle de una estación", "¿Qué tan bien predice?"]
    )
    with map_tab:
        show_map(plan)
    with plan_tab:
        show_plan(plan, day)
    with station_tab:
        show_station(plan, prediction)
    with check_tab:
        show_check(prediction, day)


main()
