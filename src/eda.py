"""Análisis exploratorio: qué hay en los datos y qué llama la atención.

Uso:
    python src/build_dataset.py   # una vez, para generar data/processed/
    python src/eda.py

Imprime los números principales y guarda los gráficos en reports/eda/ como HTML que se abren sin
conexión (comparten un único plotly.min.js en la misma carpeta).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
OUTPUT = ROOT / "reports" / "eda"

# Los perfiles por estación se calculan sobre los últimos doce meses con datos, para que reflejen
# la red actual y no estaciones que ya no existen.
RECENT_FROM = "2025-10-01"

# Hechos que cambiaron el uso del sistema y se marcan en el gráfico de evolución.
PAYMENT_START = "2021-03-13"
EVENTS = [
    {"date": "2020-03-20", "label": "Cuarentena"},
    {"date": PAYMENT_START, "label": "Empieza el cobro"},
]

DAY_TYPES = {"laborable": "Día laborable", "finde": "Fin de semana", "feriado": "Feriado"}
RAIN_BINS = [-0.01, 0, 0.5, 2, 5, 100]
RAIN_LABELS = ["Sin lluvia", "Hasta 0,5 mm", "0,5 a 2 mm", "2 a 5 mm", "Más de 5 mm"]

# Tamaño de letra pensado para proyectar: los gráficos tienen que leerse desde el fondo del aula.
LAYOUT = dict(template="plotly_white", font=dict(size=20), title_font=dict(size=26), margin=dict(t=90))


def save(figure: go.Figure, name: str) -> None:
    """Guarda un gráfico como HTML sin dependencias de red.

    :param figure: gráfico a guardar.
    :param name: nombre del archivo, sin extensión.
    """
    figure.update_layout(**LAYOUT)
    figure.write_html(OUTPUT / f"{name}.html", include_plotlyjs="directory")


def load_system_hours(station_hour: pd.DataFrame, hours: pd.DataFrame) -> pd.DataFrame:
    """Suma los viajes de todas las estaciones por hora y les agrega clima y calendario.

    :param station_hour: salidas y llegadas por estación y hora.
    :param hours: clima y calendario por hora.
    :returns: una fila por hora con los viajes del sistema y el tipo de día.
    """
    system = station_hour.groupby("hour")["departures"].sum().rename("trips").reset_index()
    system = system.merge(hours, on="hour")
    system["day_type"] = np.where(
        system["is_workday"], "laborable", np.where(system["is_weekend"], "finde", "feriado")
    )
    system["month"] = system["hour"].dt.to_period("M")
    return system


def add_expected(system: pd.DataFrame) -> pd.DataFrame:
    """Agrega a cada hora los viajes que se esperarían sin lluvia.

    Comparar horas con lluvia contra el promedio general engaña, porque la lluvia se mezcla con la
    época del año y la hora. Lo esperado es la mediana de las horas secas del mismo mes, tipo de
    día y hora del día.

    :param system: viajes del sistema por hora.
    :returns: la misma tabla con ``expected`` y ``ratio`` (real sobre esperado).
    """
    keys = ["month", "day_type", "hour_of_day"]
    dry = system[system["precipitation_mm"] == 0]
    expected = dry.groupby(keys)["trips"].median().rename("expected").reset_index()
    system = system.merge(expected, on=keys, how="left")
    system["ratio"] = system["trips"] / system["expected"]
    return system


def usage_patterns(system: pd.DataFrame) -> None:
    """Describe cuándo se usa el sistema: por tipo de día, hora y mes."""
    daily = system.groupby(["date", "day_type"])["trips"].sum().reset_index()
    print("\n== Viajes por día según tipo de día")
    print(daily.groupby("day_type")["trips"].agg(["mean", "median", "count"]).round(0).to_string())

    profile = system.groupby(["day_type", "hour_of_day"])["trips"].mean().reset_index()
    profile["Tipo de día"] = profile["day_type"].map(DAY_TYPES)
    peak = profile.loc[profile.groupby("day_type")["trips"].idxmax()]
    print("\n== Hora pico por tipo de día (viajes por hora)")
    print(peak[["day_type", "hour_of_day", "trips"]].round(0).to_string(index=False))
    figure = px.line(
        profile, x="hour_of_day", y="trips", color="Tipo de día", markers=True,
        title="En día laborable el pico de la tarde casi duplica al de la mañana",
        labels={"hour_of_day": "Hora del día", "trips": "Viajes por hora (promedio)"},
    )
    figure.update_xaxes(dtick=2)
    save(figure, "01_perfil_horario")

    workdays = system[system["is_workday"]]
    heat = workdays.pivot_table(index="day_of_week", columns="hour_of_day", values="trips", aggfunc="mean")
    heat.index = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    figure = px.imshow(
        heat, aspect="auto", color_continuous_scale="Blues",
        title="Viajes por hora en días laborables",
        labels=dict(x="Hora del día", y="", color="Viajes por hora"),
    )
    save(figure, "02_semana_hora")

    monthly = system.groupby("month").agg(trips=("trips", "sum"), days=("date", "nunique")).reset_index()
    monthly["per_day"] = monthly["trips"] / monthly["days"]
    monthly["month"] = monthly["month"].dt.to_timestamp()
    print("\n== Viajes por día, promedio por año")
    print(monthly.groupby(monthly["month"].dt.year)["per_day"].mean().round(0).to_dict())
    figure = px.line(
        monthly, x="month", y="per_day", markers=True,
        title="Viajes por día, promedio mensual",
        labels={"month": "", "per_day": "Viajes por día"},
    )
    save(figure, "03_evolucion_mensual")


def history(daily: pd.DataFrame) -> None:
    """Muestra la evolución del sistema desde 2019 y el efecto del cobro del servicio.

    :param daily: viajes por día desde 2019, con la marca de día laborable.
    """
    daily = daily.copy()
    daily["Tipo de día"] = np.where(daily["is_workday"], "Día laborable", "Fin de semana o feriado")
    monthly = (
        daily.groupby([daily["date"].dt.to_period("M").dt.to_timestamp().rename("month"), "Tipo de día"])["trips"]
        .mean().reset_index()
    )
    figure = px.line(
        monthly, x="month", y="trips", color="Tipo de día",
        title="Desde que se cobra, el fin de semana dejó de parecerse a un día laborable",
        labels={"month": "", "trips": "Viajes por día (promedio mensual)"},
    )
    for event in EVENTS:
        figure.add_vline(x=pd.Timestamp(event["date"]).timestamp() * 1000, line_dash="dash", line_color="gray",
                         annotation_text=event["label"], annotation_position="top")
    save(figure, "06_evolucion_desde_2019")

    # Cuatro semanas antes y cuatro después del inicio del cobro.
    start = pd.Timestamp(PAYMENT_START)
    window = daily[daily["date"].between(start - pd.Timedelta(days=28), start + pd.Timedelta(days=27))].copy()
    window["period"] = np.where(window["date"] < start, "antes", "después")
    # Se separa por sábado y domingo y no por feriado, porque en la ventana cae el 24 de marzo.
    window["weekend"] = np.where(window["date"].dt.day_of_week >= 5, "Sábado y domingo", "Lunes a viernes")
    change = window.groupby(["weekend", "period"])["trips"].mean().unstack()
    change["cambio %"] = 100 * (change["después"] / change["antes"] - 1)
    print(f"\n== Viajes por día, cuatro semanas antes y después del inicio del cobro ({start:%d/%m/%Y})")
    print(change.round(0).to_string())

    yearly = daily.groupby([daily["date"].dt.year.rename("year"), "Tipo de día"])["trips"].mean().unstack()
    yearly["finde / laborable"] = yearly["Fin de semana o feriado"] / yearly["Día laborable"]
    print("\n== Viajes por día según el año")
    print(yearly.round(2).to_string())


def rain_effect(system: pd.DataFrame) -> None:
    """Mide cuánto cae el uso con lluvia, respecto de lo esperado para esa hora."""
    daytime = system[system["hour_of_day"].between(6, 22) & (system["expected"] >= 50)].copy()
    daytime["rain"] = pd.cut(daytime["precipitation_mm"], RAIN_BINS, labels=RAIN_LABELS)
    daytime["Tipo de día"] = daytime["day_type"].map(DAY_TYPES)

    overall = daytime.groupby("rain", observed=True)["ratio"].agg(["median", "count"])
    print("\n== Lluvia: viajes reales sobre esperados, por intensidad en la hora (de 6 a 22)")
    print(overall.round(3).to_string())
    by_type = daytime.groupby(["Tipo de día", "rain"], observed=True)["ratio"].median().reset_index()
    by_type["change"] = (by_type["ratio"] - 1) * 100
    print(by_type.pivot(index="Tipo de día", columns="rain", values="ratio").round(3).to_string())

    shown = by_type[(by_type["rain"] != "Sin lluvia") & (by_type["Tipo de día"] != "Feriado")]
    figure = px.bar(
        shown, x="rain", y="change", color="Tipo de día", barmode="group", text_auto=".0f",
        title="Con más de 2 mm de lluvia en la hora se pierden tres de cada cuatro viajes",
        labels={"rain": "Lluvia en la hora", "change": "Cambio en los viajes (%)"},
    )
    save(figure, "04_lluvia_por_hora")

    days = (
        system[system["hour_of_day"].between(6, 22)]
        .groupby(["date", "day_type", "month"])
        .agg(trips=("trips", "sum"), rain=("precipitation_mm", "sum"))
        .reset_index()
    )
    dry_days = days[days["rain"] == 0].groupby(["month", "day_type"])["trips"].median().rename("expected")
    days = days.join(dry_days, on=["month", "day_type"])
    days["ratio"] = days["trips"] / days["expected"]
    days["rain_day"] = pd.cut(
        days["rain"], [-0.01, 0, 1, 5, 15, 500],
        labels=["Sin lluvia", "Hasta 1 mm", "1 a 5 mm", "5 a 15 mm", "Más de 15 mm"],
    )
    print("\n== Lluvia: viajes del día sobre esperados, por lluvia acumulada entre las 6 y las 22")
    print(days.groupby("rain_day", observed=True)["ratio"].agg(["median", "count"]).round(3).to_string())
    print(f"Días con más de 1 mm de lluvia: {(days['rain'] > 1).mean():.1%}")

    dry_hours = system[system["hour_of_day"].between(8, 20) & (system["precipitation_mm"] == 0)]
    feels = pd.cut(dry_hours["apparent_temperature_c"], [-10, 5, 10, 15, 20, 25, 30, 35, 50])
    print("\n== Sensación térmica en horas secas (de 8 a 20): viajes reales sobre esperados")
    print(dry_hours.groupby(feels, observed=True)["ratio"].agg(["median", "count"]).round(3).to_string())


def station_roles(station_hour: pd.DataFrame, hours: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Describe el rol de cada estación: cuánto se usa y si pierde o gana bicicletas a la mañana."""
    recent = station_hour[station_hour["hour"] >= RECENT_FROM].merge(
        hours[["hour", "date", "hour_of_day", "is_workday"]], on="hour"
    )
    workdays = recent[recent["is_workday"]].copy()
    days = workdays["date"].nunique()
    workdays["net"] = workdays["arrivals"] - workdays["departures"]

    hourly = workdays.groupby(["station_id", "hour_of_day"])[["departures", "net"]].sum() / days
    net = hourly["net"].unstack()
    roles = pd.DataFrame(
        {
            "trips_per_day": hourly["departures"].unstack().sum(axis=1),
            "net_morning": net.loc[:, 6:10].sum(axis=1),
            "net_evening": net.loc[:, 16:20].sum(axis=1),
        }
    ).join(stations.set_index("station_id"), how="inner")
    roles["morning_pct_capacity"] = 100 * roles["net_morning"] / roles["capacity"].astype(float)

    columns = ["name", "zone", "capacity", "trips_per_day", "net_morning", "net_evening"]
    print(f"\n== Estaciones en días laborables, desde {RECENT_FROM} ({days} días, {len(roles)} estaciones)")
    print("Las que más bicicletas pierden entre las 6 y las 11:")
    print(roles.nsmallest(8, "net_morning")[columns].round(1).to_string())
    print("Las que más bicicletas ganan entre las 6 y las 11:")
    print(roles.nlargest(8, "net_morning")[columns].round(1).to_string())
    top = roles["trips_per_day"].nlargest(len(roles) // 10).sum() / roles["trips_per_day"].sum()
    print(f"El 10% de las estaciones más usadas concentra el {top:.1%} de los viajes")

    surroundings = ["bike_lane_distance_m", "bike_lane_m_within_300m", "subway_distance_m", "train_distance_m"]
    print("\n== Relación (Spearman) entre el entorno y el uso de la estación")
    print(roles[["trips_per_day", "net_morning"] + surroundings].corr(method="spearman").loc[
        ["trips_per_day", "net_morning"], surroundings].round(2).to_string())

    figure = px.scatter_map(
        roles.reset_index(), lat="lat", lon="lon", color="net_morning", size="trips_per_day",
        hover_name="name", hover_data={"capacity": True, "net_morning": ":.1f", "trips_per_day": ":.0f"},
        color_continuous_scale="RdBu", color_continuous_midpoint=0, range_color=[-8, 8],
        zoom=11.3, height=850, map_style="carto-positron",
        title="A la mañana las bicicletas van de las terminales y los barrios al centro y Puerto Madero",
        labels={"net_morning": "Bicicletas ganadas<br>de 6 a 11", "trips_per_day": "Viajes por día"},
    )
    save(figure, "05_mapa_flujo_manana")

    # Vaivén del stock: cuánto sube y baja la cantidad de bicicletas de una estación en un día,
    # reconstruido como el acumulado de llegadas menos salidas.
    workdays = workdays.sort_values(["station_id", "hour"])
    workdays["cumulative"] = workdays.groupby(["station_id", "date"])["net"].cumsum()
    swing = workdays.groupby(["station_id", "date"])["cumulative"].agg(["min", "max"])
    swing["swing"] = swing["max"].clip(lower=0) - swing["min"].clip(upper=0)
    swing = swing.join(stations.set_index("station_id")["capacity"].astype(float)).dropna()
    swing["pct"] = swing["swing"] / swing["capacity"]
    print("\n== Vaivén diario de bicicletas de una estación, como proporción de su capacidad")
    print(swing["pct"].describe(percentiles=[0.5, 0.75, 0.9, 0.99]).round(2).to_dict())
    print(f"Días-estación con vaivén de al menos la mitad de la capacidad: {(swing['pct'] >= 0.5).mean():.1%}")
    print(f"Días-estación con vaivén de al menos toda la capacidad: {(swing['pct'] >= 1).mean():.1%}")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    station_hour = pd.read_parquet(PROCESSED / "station_hour.parquet")
    hours = pd.read_parquet(PROCESSED / "hours.parquet")
    stations = pd.read_parquet(PROCESSED / "stations.parquet")

    print(f"Período: {hours['hour'].min()} a {hours['hour'].max()}")
    print(f"Viajes: {int(station_hour['departures'].sum()):,}; estaciones: {len(stations)}")

    system = add_expected(load_system_hours(station_hour, hours))
    usage_patterns(system)
    history(pd.read_parquet(PROCESSED / "daily_history.parquet"))
    rain_effect(system)
    station_roles(station_hour, hours, stations)
    print(f"\nGráficos en {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
