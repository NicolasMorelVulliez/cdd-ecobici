"""Arma el reporte general del trabajo en un solo archivo HTML.

Uso:
    python src/build_report.py

Guarda reports/informe.html. Es un único archivo que abre sin conexión: lleva adentro los gráficos,
los datos y una predicción interactiva. Necesita haber corrido antes build_dataset.py,
cluster_stations.py, train_demand.py y compare_models.py.

La plantilla está en src/report_template.html; este script calcula los números, arma los gráficos
y los reemplaza en la plantilla.
"""

import json
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

import cluster_stations
import eda
import forecast

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROCESSED = DATA / "processed"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
TEMPLATE = Path(__file__).resolve().parent / "report_template.html"

# Colores: los tres primeros de una paleta categórica validada para daltonismo, más grises.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#7c7b76", "#ececea"
DIVERGING = [[0, ORANGE], [0.5, "#e6e5e1"], [1, BLUE]]

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre"]
MAP_CENTER = {"lat": -34.607, "lon": -58.44}

SOURCES = [
    ("Recorridos de Ecobici", "Un viaje por fila: estación y hora de origen y destino", "Buenos Aires Data"),
    ("Clima horario", "Lluvia, temperatura, viento y nubosidad de cada hora", "Open-Meteo"),
    ("Feriados", "Para distinguir un día laborable de un feriado", "argentina.gob.ar, ArgentinaDatos y nolaborables"),
    ("Estaciones actuales", "Ubicación y capacidad de cada estación", "Feed GBFS de BA Ecobici"),
    ("Ecobici 2010–2019", "Capacidad de estaciones que ya no existen y red de ciclovías de 2019", "CONICET Digital"),
    ("Ciclovías", "Red actual, para medir cuánta ciclovía rodea a cada estación", "Buenos Aires Data"),
    ("Subte, tren y Metrobus", "Distancia de cada estación al transporte masivo", "Buenos Aires Data"),
    ("Usuarios de Ecobici", "Edad y género. Se revisó y no se usa: los identificadores anteriores a 2020 se repiten",
     "Buenos Aires Data"),
]

# Escenarios de la predicción interactiva.
SIM_DAYS = ["Día laborable", "Sábado o domingo", "Feriado"]
SIM_RAIN = [("Sin lluvia", 0.0), ("Llovizna (0,3 mm por hora)", 0.3), ("Lluvia (1,5 mm por hora)", 1.5),
            ("Lluvia fuerte (4 mm por hora)", 4.0)]
SIM_WINDOWS = [("A la mañana (de 7 a 12 h)", 7, 11), ("A la tarde (de 14 a 19 h)", 14, 18),
               ("Todo el día (de 7 a 20 h)", 7, 19)]
SIM_TEMPERATURES = [("5 °C menos que lo normal", -5), ("Normal para el mes", 0), ("5 °C más que lo normal", 5)]
SIM_YEAR = 2026
SIM_LIST_SIZE = 6

FEATURE_LABELS = {
    "usual_departures": "Salidas habituales a esa hora", "usual_arrivals": "Llegadas habituales a esa hora",
    "recent_daily_departures": "Nivel de las últimas 4 semanas", "hour_of_day": "Hora del día",
    "day_of_week": "Día de la semana", "month": "Mes", "is_workday": "Es día laborable", "is_holiday": "Es feriado",
    "precipitation_mm": "Lluvia en la hora", "precipitation_prev_3h": "Lluvia de las 3 horas previas",
    "apparent_temperature_c": "Sensación térmica", "wind_speed_kmh": "Viento", "cloud_cover_pct": "Nubosidad",
    "cluster": "Tipo de estación", "capacity": "Capacidad", "lon": "Ubicación (este-oeste)",
    "lat": "Ubicación (norte-sur)", "subway_distance_m": "Distancia al subte",
    "bike_lane_m_within_300m": "Ciclovías alrededor",
}


# ---------------------------------------------------------------------------------------------
# Formato de números y textos
# ---------------------------------------------------------------------------------------------

def integer(value: float) -> str:
    """Formatea un entero con punto de miles."""
    return f"{value:,.0f}".replace(",", ".")


def decimal(value: float, digits: int = 2) -> str:
    """Formatea un número con coma decimal."""
    return f"{value:,.{digits}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def percent(value: float, digits: int = 0) -> str:
    """Formatea una proporción (0 a 1) como porcentaje."""
    return decimal(100 * value, digits) + "%"


def signed_percent(value: float) -> str:
    """Formatea un cambio relativo con su signo, usando el signo menos tipográfico."""
    text = f"{100 * value:+.0f}%"
    return text.replace("-", "−")


def long_date(value) -> str:
    """Escribe una fecha como «13 de marzo de 2021»."""
    value = pd.Timestamp(value)
    return f"{value.day} de {MONTHS[value.month - 1]} de {value.year}"


def station_label(name: str) -> str:
    """Limpia el nombre de una estación: saca el número y normaliza las mayúsculas.

    :param name: nombre como figura en los recorridos, por ejemplo «130 - RETIRO II».
    :returns: el nombre legible, por ejemplo «Retiro II».
    """
    text = name.split("-", 1)[-1].strip()
    if not text.isupper():
        return text
    small = {"de", "del", "la", "las", "los", "y", "el"}
    words = []
    for position, word in enumerate(text.split()):
        lower = word.lower()
        if set(word) <= set("IVX"):
            words.append(word)
        elif lower in small and position > 0:
            words.append(lower)
        else:
            words.append(lower.capitalize())
    return " ".join(words)


def join_names(names: list[str]) -> str:
    """Une nombres con comas y una «y» final."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


# ---------------------------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------------------------

def styled(figure: go.Figure, height: int = 420, **layout) -> dict:
    """Aplica el estilo común a un gráfico y lo devuelve listo para incrustar.

    :param figure: gráfico de Plotly.
    :param height: alto en píxeles.
    :param layout: ajustes adicionales del diseño.
    :returns: el gráfico como diccionario serializable.
    """
    figure.update_layout(
        template="plotly_white", height=height, margin=dict(l=56, r=18, t=18, b=48), paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(family='system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', size=15, color=INK),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=14)),
        separators=",.", hoverlabel=dict(font_size=14),
    )
    figure.update_xaxes(gridcolor=GRID, linecolor="#c9c8c3", tickfont=dict(color="#52514e"), zeroline=False)
    figure.update_yaxes(gridcolor=GRID, linecolor="white", tickfont=dict(color="#52514e"), zerolinecolor="#c9c8c3")
    figure.update_layout(**layout)
    return json.loads(figure.to_json())


def history_figure(daily: pd.DataFrame) -> dict:
    """Evolución de los viajes por día desde 2019, con los hechos que la cambiaron."""
    daily = daily.assign(month=daily["date"].dt.to_period("M").dt.to_timestamp())
    monthly = daily.groupby(["month", "is_workday"])["trips"].mean().unstack()
    figure = go.Figure()
    for workday, name, color in ((True, "Día laborable", BLUE), (False, "Fin de semana o feriado", ORANGE)):
        figure.add_scatter(x=monthly.index, y=monthly[workday].round(0), name=name, mode="lines",
                           line=dict(color=color, width=2), hovertemplate="%{y:,.0f} viajes por día<extra>" + name + "</extra>")
    top = float(monthly.max().max())
    for event in eda.EVENTS:
        figure.add_shape(type="line", x0=event["date"], x1=event["date"], y0=0, y1=top, line=dict(color=MUTED, width=1, dash="dash"))
        figure.add_annotation(x=event["date"], y=top, text=event["label"], showarrow=False, yshift=12, font=dict(size=13, color="#52514e"))
    return styled(figure, hovermode="x unified", yaxis_title="Viajes por día", margin=dict(l=62, r=18, t=34, b=40))


def hourly_figure(system: pd.DataFrame) -> dict:
    """Viajes por hora según el tipo de día."""
    profile = system.groupby(["day_type", "hour_of_day"])["trips"].mean().unstack(0)
    figure = go.Figure()
    for key, name, color in (("laborable", "Día laborable", BLUE), ("finde", "Fin de semana", ORANGE), ("feriado", "Feriado", AQUA)):
        figure.add_scatter(x=profile.index, y=profile[key].round(0), name=name, mode="lines+markers",
                           line=dict(color=color, width=2), marker=dict(size=7),
                           hovertemplate="%{y:,.0f} viajes<extra>" + name + "</extra>")
    return styled(figure, hovermode="x unified", xaxis=dict(title="Hora del día", dtick=2), yaxis_title="Viajes por hora")


def rain_table(system: pd.DataFrame) -> pd.DataFrame:
    """Viajes reales sobre esperados según la lluvia de la hora, por tipo de día y en total."""
    daytime = system[system["hour_of_day"].between(6, 22) & (system["expected"] >= 50)].copy()
    daytime["rain"] = pd.cut(daytime["precipitation_mm"], eda.RAIN_BINS, labels=eda.RAIN_LABELS)
    by_type = daytime.groupby(["day_type", "rain"], observed=True)["ratio"].median().unstack(0)
    by_type["total"] = daytime.groupby("rain", observed=True)["ratio"].median()
    return by_type


def rain_figure(table: pd.DataFrame) -> dict:
    """Cambio en los viajes según la lluvia de la hora."""
    shown = table.drop(index="Sin lluvia")
    figure = go.Figure()
    for key, name, color in (("laborable", "Día laborable", BLUE), ("finde", "Fin de semana", ORANGE)):
        change = (100 * (shown[key] - 1)).round(0)
        figure.add_bar(x=[str(label) for label in shown.index], y=change, name=name, marker_color=color,
                       text=[f"{value:.0f}%".replace("-", "−") for value in change], textposition="outside",
                       textfont=dict(color=INK), hovertemplate="%{y:.0f}%<extra>" + name + "</extra>")
    return styled(figure, barmode="group", bargap=0.3, bargroupgap=0.08, xaxis_title="Lluvia en la hora",
                  yaxis=dict(title="Cambio en los viajes (%)", range=[-100, 8]))


def station_roles(station_hour: pd.DataFrame, hours: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Viajes por día y bicicletas que gana o pierde cada estación a la mañana de un día laborable."""
    recent = station_hour[station_hour["hour"] >= eda.RECENT_FROM].merge(
        hours[["hour", "date", "hour_of_day", "is_workday"]], on="hour"
    )
    workdays = recent[recent["is_workday"]]
    days = workdays["date"].nunique()
    totals = workdays.groupby(["station_id", "hour_of_day"])[["departures", "arrivals"]].sum() / days
    net = (totals["arrivals"] - totals["departures"]).unstack()
    roles = pd.DataFrame({
        "trips_per_day": totals["departures"].unstack().sum(axis=1),
        "net_morning": net.loc[:, 6:10].sum(axis=1),
    })
    return roles.join(stations.set_index("station_id"), how="inner").reset_index()


def map_figure(roles: pd.DataFrame) -> dict:
    """Mapa de las estaciones según las bicicletas que ganan o pierden a la mañana."""
    with (DATA / "road" / "ciclovias.geojson").open(encoding="utf-8") as file:
        lanes = json.load(file)["features"]
    lons, lats = [], []
    for lane in lanes:
        for lon, lat in lane["geometry"]["coordinates"]:
            lons.append(round(lon, 5))
            lats.append(round(lat, 5))
        lons.append(None)
        lats.append(None)
    figure = go.Figure()
    figure.add_trace(go.Scattermap(lon=lons, lat=lats, mode="lines", line=dict(color="#c9c8c3", width=1),
                                   hoverinfo="skip", showlegend=False))
    hover = [
        f"<b>{escape(station_label(row.name))}</b><br>"
        f"{decimal(row.net_morning, 1).replace('-', '−')} bicicletas de 6 a 11<br>{row.trips_per_day:.0f} viajes por día"
        for row in roles.itertuples()
    ]
    figure.add_trace(go.Scattermap(
        lon=roles["lon"], lat=roles["lat"], mode="markers", text=hover, hovertemplate="%{text}<extra></extra>",
        showlegend=False,
        marker=dict(size=roles["trips_per_day"], sizemode="area", sizeref=2 * roles["trips_per_day"].max() / 26 ** 2,
                    sizemin=4, color=roles["net_morning"], colorscale=DIVERGING, cmin=-8, cmax=8, opacity=0.9,
                    colorbar=dict(title=dict(text="Bicicletas", side="top"), thickness=12, len=0.5, x=0.99, xanchor="right",
                                  y=0.5, tickvals=[-8, 0, 8], ticktext=["pierde 8", "0", "gana 8"])),
    ))
    return styled(figure, height=640, margin=dict(l=0, r=0, t=0, b=0), map=dict(style="white-bg", center=MAP_CENTER, zoom=11.2))


def cluster_figure(profile: pd.DataFrame, clusters: pd.DataFrame) -> dict:
    """Perfil horario de salidas y llegadas de cada tipo de estación."""
    names = clusters.drop_duplicates("cluster").sort_values("cluster").set_index("cluster")["cluster_name"]
    sizes = clusters["cluster"].value_counts()
    assignment = clusters.set_index("station_id")["cluster"].reindex(profile.index)
    titles = [f"{names[cluster]} ({sizes[cluster]})" for cluster in names.index]
    figure = make_subplots(rows=1, cols=len(names), shared_yaxes=True, subplot_titles=titles, horizontal_spacing=0.02)
    for column, cluster in enumerate(names.index, start=1):
        for prefix, name, color in (("dep_", "Salidas", ORANGE), ("arr_", "Llegadas", BLUE)):
            curve = profile.filter(like=prefix).set_axis(range(24), axis=1)[assignment == cluster].mean()
            figure.add_scatter(x=list(range(24)), y=(100 * curve).round(2), name=name, mode="lines", legendgroup=name,
                               showlegend=column == 1, line=dict(color=color, width=2), row=1, col=column,
                               hovertemplate="%{x} h: %{y:.1f}% del día<extra>" + name + "</extra>")
    figure.update_xaxes(tickvals=[0, 6, 12, 18], title_text="Hora")
    figure.update_annotations(font_size=14)
    return styled(figure, height=340, margin=dict(l=56, r=10, t=46, b=48), yaxis_title="% del día",
                  legend=dict(orientation="h", yanchor="bottom", y=1.13, xanchor="left", x=0))


def silhouette_scores(features: pd.DataFrame) -> dict:
    """Índice de silueta para cada cantidad de grupos candidata."""
    scaled = StandardScaler().fit_transform(features[cluster_stations.FEATURES])
    scores = {}
    for groups in cluster_stations.CANDIDATE_GROUPS:
        labels = KMeans(groups, n_init=20, random_state=cluster_stations.RANDOM_STATE).fit_predict(scaled)
        scores[groups] = float(silhouette_score(scaled, labels))
    return scores


def silhouette_figure(scores: dict, chosen: int) -> dict:
    """Silueta según la cantidad de grupos, con la elegida resaltada."""
    groups = list(scores)
    colors = [BLUE if group == chosen else "#b7d3f6" for group in groups]
    figure = go.Figure(go.Bar(
        x=[str(group) for group in groups], y=[round(scores[group], 3) for group in groups], marker_color=colors,
        text=[decimal(scores[group]) for group in groups], textposition="outside", textfont=dict(color=INK),
        hovertemplate="%{x} grupos: %{y:.3f}<extra></extra>",
    ))
    return styled(figure, height=300, bargap=0.35, xaxis_title="Cantidad de grupos",
                  yaxis=dict(title="Silueta", range=[0, max(scores.values()) * 1.25]), showlegend=False)


def regression_figure(rows: list[dict]) -> dict:
    """Error de cada algoritmo, en general y con lluvia."""
    ordered = sorted(rows, key=lambda row: row["mae_rain"], reverse=True)
    names = [row["model"] for row in ordered]
    figure = go.Figure()
    for key, name, color in (("mae", "Todas las horas", BLUE), ("mae_rain", "Horas con lluvia", ORANGE)):
        values = [round(row[key], 3) for row in ordered]
        figure.add_bar(y=names, x=values, name=name, orientation="h", marker_color=color,
                       text=[decimal(value, 3) for value in values], textposition="outside", textfont=dict(color=INK),
                       hovertemplate="%{x:.3f} viajes<extra>" + name + "</extra>")
    top = max(max(row["mae"], row["mae_rain"]) for row in rows)
    return styled(figure, height=470, barmode="group", bargap=0.28, bargroupgap=0.06, margin=dict(l=250, r=30, t=18, b=48),
                  xaxis=dict(title="Error absoluto medio (viajes por estación y hora)", range=[0, top * 1.15]),
                  legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, traceorder="reversed"))


def classification_figure(rows: list[dict]) -> dict:
    """Precisión, recall y F1 de cada algoritmo de clasificación."""
    ordered = sorted((row for row in rows if row["f1"] > 0), key=lambda row: row["f1"])
    names = [row["model"] for row in ordered]
    figure = go.Figure()
    for key, name, color in (("precision", "Precisión", BLUE), ("recall", "Recall", ORANGE), ("f1", "F1", AQUA)):
        values = [round(row[key], 3) for row in ordered]
        figure.add_bar(x=names, y=values, name=name, marker_color=color, text=[decimal(value) for value in values],
                       textposition="outside", textfont=dict(color=INK, size=13),
                       hovertemplate="%{y:.3f}<extra>" + name + "</extra>")
    return styled(figure, height=420, barmode="group", bargap=0.25, bargroupgap=0.06, yaxis=dict(range=[0, 0.85]))


def daily_figure(evaluation: dict) -> dict:
    """Viajes por día en el período de prueba: real, modelo y referencia."""
    daily = pd.DataFrame(evaluation["daily"])
    figure = go.Figure()
    for column, name, line in (
        ("adjusted", "Uso habitual ajustado", dict(color="#a9a8a2", width=2, dash="dot")),
        ("model", "Modelo", dict(color=BLUE, width=2)),
        ("actual", "Real", dict(color=INK, width=2.5)),
    ):
        figure.add_scatter(x=daily["date"], y=daily[column].round(0), name=name, mode="lines", line=line,
                           hovertemplate="%{y:,.0f} viajes<extra>" + name + "</extra>")
    for day in daily.loc[daily["rain"] >= 5, "date"]:
        start = pd.Timestamp(day) - pd.Timedelta(hours=12)
        figure.add_vrect(x0=start.isoformat(), x1=(start + pd.Timedelta(days=1)).isoformat(), fillcolor=BLUE,
                         opacity=0.1, line_width=0)
    return styled(figure, hovermode="x unified", yaxis=dict(title="Viajes por día", rangemode="tozero"),
                  legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, traceorder="reversed"))


def importance_figure(importance: dict) -> dict:
    """Variables que más pesan en el modelo."""
    top = sorted(importance.items(), key=lambda item: item[1], reverse=True)[:8][::-1]
    figure = go.Figure(go.Bar(
        y=[FEATURE_LABELS.get(name, name) for name, _ in top], x=[value for _, value in top], orientation="h",
        marker_color=BLUE, hovertemplate="%{x:.3f} viajes más de error<extra></extra>",
    ))
    return styled(figure, height=340, margin=dict(l=230, r=20, t=10, b=48), xaxis_title="Aumento del error (viajes)",
                  showlegend=False)


# ---------------------------------------------------------------------------------------------
# Tablas en HTML
# ---------------------------------------------------------------------------------------------

def regression_rows(rows: list[dict]) -> str:
    """Filas de la tabla de regresión."""
    html = []
    for row in rows:
        css = "chosen" if row["kind"] == "completo" else "reference" if row["kind"] == "referencia" else ""
        seconds = "—" if row["kind"] == "referencia" else f"{row['seconds']:.0f} s"
        html.append(
            f'<tr class="{css}"><td>{escape(row["model"])}</td><td class="num">{decimal(row["mae"], 3)}</td>'
            f'<td class="num">{decimal(row["mae_rain"], 3)}</td><td class="num">{decimal(row["rmse"], 3)}</td>'
            f'<td class="num">{decimal(row["r2"], 3)}</td><td class="num">{percent(row["daily_error"], 1)}</td>'
            f'<td class="num">{seconds}</td></tr>'
        )
    return "\n".join(html)


def classification_rows(rows: list[dict]) -> str:
    """Filas de la tabla de clasificación."""
    html = []
    for row in rows:
        css = "chosen" if row["model"] == "Gradient boosting" else "reference" if row["kind"] == "referencia" else ""
        seconds = "—" if row["kind"] == "referencia" else f"{row['seconds']:.0f} s"
        auc = "—" if row["auc"] is None else decimal(row["auc"], 3)
        html.append(
            f'<tr class="{css}"><td>{escape(row["model"])}</td><td class="num">{percent(row["accuracy"], 1)}</td>'
            f'<td class="num">{decimal(row["precision"], 3)}</td><td class="num">{decimal(row["recall"], 3)}</td>'
            f'<td class="num">{decimal(row["f1"], 3)}</td><td class="num">{auc}</td><td class="num">{seconds}</td></tr>'
        )
    return "\n".join(html)


def cluster_rows(clusters: pd.DataFrame, stations: pd.DataFrame) -> str:
    """Filas de la tabla de tipos de estación."""
    named = clusters.merge(stations[["station_id", "name"]], on="station_id")
    html = []
    for (_, name), members in named.groupby(["cluster", "cluster_name"]):
        examples = join_names([station_label(value) for value in members.nlargest(3, "trips_per_day")["name"]])
        balance = signed_percent(members["morning_balance"].mean())
        html.append(
            f"<tr><td><b>{escape(name)}</b></td><td class='num'>{len(members)}</td>"
            f"<td class='num'>{decimal(members['trips_per_day'].mean(), 0)}</td><td class='num'>{balance}</td>"
            f"<td class='num'>{decimal(members['weekend_ratio'].mean())}</td><td>{escape(examples)}</td></tr>"
        )
    return "\n".join(html)


def choice_text(comparison: dict) -> str:
    """Explica la elección del algoritmo con los números de la comparación."""
    regression = {row["model"]: row for row in comparison["regression"]}
    classification = {row["model"]: row for row in comparison["classification"]}
    boosting, network, forest = regression["Gradient boosting"], regression["Red neuronal"], regression["Random forest"]
    linear, full = regression["Regresión lineal"], regression["Gradient boosting (todos los datos)"]
    reference = regression["Uso habitual ajustado"]
    # Los tiempos dependen de la carga de la máquina, así que la velocidad solo se presenta como
    # ventaja si en esta corrida el gradient boosting fue realmente el más rápido de los tres.
    times = (f"Con la misma muestra entrenó en {boosting['seconds']:.0f} segundos, contra {network['seconds']:.0f} de la "
             f"red neuronal y {forest['seconds']:.0f} del random forest. Los tiempos varían según la carga de la máquina.")
    fastest = boosting["seconds"] < min(network["seconds"], forest["seconds"])
    speed_row = f"<tr><td>{'Es el más rápido de los tres' if fastest else 'Tiempo de entrenamiento'}</td><td>{times}</td></tr>"
    reasons = "cuatro" if fastest else "tres"
    return f"""
  <p><b>No hay un ganador claro en precisión.</b> Con la misma muestra, el gradient boosting, el random forest y la red
  neuronal quedan casi empatados: {decimal(boosting['mae'], 3)}, {decimal(forest['mae'], 3)} y {decimal(network['mae'], 3)}
  viajes de error por estación y hora. En clasificación pasa lo mismo: la red neuronal tiene un F1 de
  {decimal(classification['Red neuronal']['f1'], 3)} y el gradient boosting de {decimal(classification['Gradient boosting']['f1'], 3)}.</p>
  <p>Los modelos simples sí quedan atrás donde importa. La regresión lineal iguala al resto en horas normales, pero con
  lluvia su error es {decimal(linear['mae_rain'], 3)} contra {decimal(boosting['mae_rain'], 3)}: no puede aprender que la lluvia
  pesa distinto según la hora y la estación.</p>
  <p>Se eligió gradient boosting por {reasons} razones prácticas:</p>
  <div class="scroll"><table>
    <thead><tr><th>Razón</th><th>Detalle</th></tr></thead>
    <tbody>
      <tr><td>Puede usar todos los datos</td><td>Con las {integer(comparison['train_rows'])} filas completas entrena en
        {full['seconds']:.0f} segundos y baja el error en los viajes del día de {percent(boosting['daily_error'], 1)} a
        {percent(full['daily_error'], 1)}. La referencia tiene {percent(reference['daily_error'], 1)}.</td></tr>
      <tr><td>Necesita menos preparación</td><td>Acepta valores faltantes (estaciones sin capacidad o sin tipo) y variables en
        cualquier escala. La red neuronal y los modelos lineales necesitan completar faltantes y estandarizar.</td></tr>
      <tr><td>Está hecho para conteos</td><td>Usa pérdida de Poisson, pensada para cantidades chicas con muchos ceros, que es
        lo que son las salidas de una estación en una hora.</td></tr>
      {speed_row}
    </tbody>
  </table></div>
  <p>Si la prioridad fuera solo el error con lluvia, la red neuronal sería una opción válida
  ({decimal(network['mae_rain'], 3)} contra {decimal(boosting['mae_rain'], 3)}), a cambio de más preparación de los datos
  y de no poder entrenar con todas las filas en un tiempo razonable.</p>"""


# ---------------------------------------------------------------------------------------------
# Predicción interactiva
# ---------------------------------------------------------------------------------------------

def scenario_date(month: int, day_type: int) -> pd.Timestamp:
    """Elige un día representativo del mes: un miércoles o un sábado de mitad de mes."""
    weekday = 5 if day_type == 1 else 2
    days = pd.date_range(f"{SIM_YEAR}-{month:02d}-10", periods=7)
    return next(day for day in days if day.day_of_week == weekday)


def build_scenarios(resources: forecast.Resources) -> dict:
    """Calcula todos los escenarios de la predicción interactiva.

    :param resources: tablas y modelos cargados.
    :returns: los escenarios y las opciones de los selectores, listos para incrustar.
    """
    stations = resources.stations.dropna(subset=["capacity"]).reset_index(drop=True)
    position = {station_id: index for index, station_id in enumerate(stations["station_id"])}
    scenarios = {}
    started = time.time()
    for day_type in range(len(SIM_DAYS)):
        for month in range(1, 13):
            date = scenario_date(month, day_type)
            base = forecast.typical_weather(resources, date)
            for temperature_index, (_, shift) in enumerate(SIM_TEMPERATURES):
                for rain_index, (_, amount) in enumerate(SIM_RAIN):
                    for window_index, (_, start, end) in enumerate(SIM_WINDOWS):
                        if amount == 0 and window_index > 0:
                            continue
                        weather = base.copy()
                        weather["apparent_temperature_c"] += shift
                        weather.loc[weather["hour_of_day"].between(start, end), "precipitation_mm"] = amount
                        prediction = forecast.predict_day(resources, date, weather, day_type == 2)
                        plan = forecast.plan_day(prediction, resources.stations)
                        hourly = prediction.groupby("hour_of_day")["departures"].sum()
                        loaded = plan[plan["status"] == "Arrancar cargada"].nlargest(SIM_LIST_SIZE, "bikes_needed")
                        room = plan[plan["status"] == "Arrancar con lugar"].nlargest(SIM_LIST_SIZE, "docks_needed")
                        counts = plan["status"].value_counts()
                        key = f"{day_type}|{month - 1}|{rain_index}|{window_index}|{temperature_index}"
                        scenarios[key] = {
                            "hourly": [int(round(value)) for value in hourly],
                            "total": int(round(hourly.sum())),
                            "loaded": int(counts.get("Arrancar cargada", 0)),
                            "room": int(counts.get("Arrancar con lugar", 0)),
                            "visit": int(counts.get("Necesita visita durante el día", 0)),
                            "load_list": [[position[row.station_id], int(row.target_stock)] for row in loaded.itertuples()],
                            "room_list": [[position[row.station_id], int(row.target_stock)] for row in room.itertuples()],
                        }
        print(f"  escenarios de «{SIM_DAYS[day_type]}»: {len(scenarios)} ({time.time() - started:.0f} s)", flush=True)

    layout = styled(go.Figure(), height=380, hovermode="x unified", xaxis=dict(title="Hora del día", dtick=2),
                    yaxis=dict(title="Viajes por hora", rangemode="tozero"))["layout"]
    return {
        "options": {
            "day": SIM_DAYS, "month": [name.capitalize() for name in MONTHS], "rain": [label for label, _ in SIM_RAIN],
            "window": [label for label, _, _ in SIM_WINDOWS], "temp": [label for label, _ in SIM_TEMPERATURES],
        },
        "windows": [[start, end] for _, start, end in SIM_WINDOWS],
        "default_month": 9, "default_temp": 1,
        "stations": [[station_label(row.name), int(row.capacity)] for row in stations.itertuples()],
        "scenarios": scenarios, "layout": layout,
    }


# ---------------------------------------------------------------------------------------------
# Armado
# ---------------------------------------------------------------------------------------------

def main() -> int:
    started = time.time()
    REPORTS.mkdir(parents=True, exist_ok=True)
    station_hour = pd.read_parquet(PROCESSED / "station_hour.parquet")
    hours = pd.read_parquet(PROCESSED / "hours.parquet")
    stations = pd.read_parquet(PROCESSED / "stations.parquet")
    daily = pd.read_parquet(PROCESSED / "daily_history.parquet")
    clusters = pd.read_parquet(PROCESSED / "station_clusters.parquet")
    summary = json.loads((PROCESSED / "build_summary.json").read_text(encoding="utf-8"))
    evaluation = json.loads((MODELS / "evaluation.json").read_text(encoding="utf-8"))
    comparison = json.loads((REPORTS / "models" / "model_comparison.json").read_text(encoding="utf-8"))

    system = eda.add_expected(eda.load_system_hours(station_hour, hours))
    roles = station_roles(station_hour, hours, stations)
    rain = rain_table(system)
    features, profile = cluster_stations.build_features(station_hour, hours)
    scores = silhouette_scores(features)
    chosen_k = int(clusters["cluster"].nunique())
    best_k = max(scores, key=scores.get)

    # ---- Números del texto
    workday_profile = system[system["day_type"] == "laborable"].groupby("hour_of_day")["trips"].mean()
    morning = workday_profile.loc[6:10]
    per_day = system.groupby(["date", "day_type"])["trips"].sum().groupby("day_type").mean()
    days = system[system["hour_of_day"].between(6, 22)].groupby("date")["precipitation_mm"].sum()

    payment = pd.Timestamp(eda.PAYMENT_START)
    window = daily[daily["date"].between(payment - pd.Timedelta(days=28), payment + pd.Timedelta(days=27))]
    weekend = window["date"].dt.day_of_week >= 5
    after = window["date"] >= payment
    drop = lambda mask: window.loc[mask & after, "trips"].mean() / window.loc[mask & ~after, "trips"].mean() - 1

    surroundings = roles[["trips_per_day", "subway_distance_m", "bike_lane_m_within_300m"]].corr(method="spearman")
    hourly = {(row["variable"], row["horas"]): row for row in evaluation["hourly_errors"]}
    all_hours, rain_hours = hourly[("departures", "todas las horas")], hourly[("departures", "horas con lluvia")]
    rainy_key = next(key for key in evaluation["daily_errors"] if key != "todos los días")
    all_days, rainy_days = evaluation["daily_errors"]["todos los días"], evaluation["daily_errors"][rainy_key]
    balance = evaluation["morning_balance_errors"]
    majority = next(row for row in comparison["classification"] if row["model"] == "Decir siempre que no")

    print("Calculando los escenarios de la predicción interactiva…", flush=True)
    scenarios = build_scenarios(forecast.load_resources())

    figures = {
        "fig-history": history_figure(daily),
        "fig-hourly": hourly_figure(system),
        "fig-rain": rain_figure(rain),
        "fig-map": map_figure(roles),
        "fig-clusters": cluster_figure(profile, clusters),
        "fig-silhouette": silhouette_figure(scores, chosen_k),
        "fig-regression": regression_figure(comparison["regression"]),
        "fig-classification": classification_figure(comparison["classification"]),
        "fig-daily": daily_figure(evaluation),
        "fig-importance": importance_figure(evaluation["importance"]),
    }

    trips_from, trips_to = station_hour["hour"].min(), station_hour["hour"].max()
    facts = {
        "trips_millions": decimal(summary["trips_kept"] / 1e6, 1),
        "peak_hour": str(int(workday_profile.idxmax())),
        "peak_trips": integer(workday_profile.max()),
        "peak_ratio": decimal(workday_profile.max() / morning.max(), 1),
        "morning_peak_hour": str(int(morning.idxmax())),
        "morning_peak_trips": integer(morning.max()),
        "workday_trips": integer(per_day["laborable"]),
        "weekend_trips": integer(per_day["finde"]),
        "top_origins": join_names([station_label(name) for name in roles.nsmallest(3, "net_morning")["name"]]),
        "top_destinations": join_names([station_label(name) for name in roles.nlargest(3, "net_morning")["name"]]),
        "rain_light_drop": percent(1 - rain.loc["Hasta 0,5 mm", "total"]),
        "rain_mid_drop": percent(1 - rain.loc["0,5 a 2 mm", "total"]),
        "rain_heavy_drop": percent(1 - rain.loc["2 a 5 mm", "total"]),
        "rain_heavy_change": signed_percent(rain.loc["2 a 5 mm", "total"] - 1),
        "rainy_days_share": percent((days > 1).mean()),
        "payment_date": long_date(payment),
        "payment_weekend_drop": percent(-drop(weekend)),
        "payment_weekday_drop": percent(-drop(~weekend)),
        "source_count": str(len(SOURCES)),
        "sources_rows": "\n".join(
            f"<tr><td><b>{escape(name)}</b></td><td>{escape(what)}</td><td>{escape(origin)}</td></tr>"
            for name, what, origin in SOURCES
        ),
        "trips_from": long_date(trips_from), "trips_to": long_date(trips_to),
        "trips_from_year": str(trips_from.year), "trips_to_year": str(trips_to.year),
        "data_end": long_date(hours["hour"].max()),
        "trips_read": integer(summary["trips_read"]), "trips_kept": integer(summary["trips_kept"]),
        "corr_subway": decimal(surroundings.loc["trips_per_day", "subway_distance_m"]).replace("-", "−"),
        "corr_lanes": decimal(surroundings.loc["trips_per_day", "bike_lane_m_within_300m"]),
        "clustered_stations": str(len(clusters)),
        "cluster_count": str(chosen_k),
        "cluster_rows": cluster_rows(clusters, stations),
        "best_k": str(best_k), "best_k_score": decimal(scores[best_k]), "chosen_k_score": decimal(scores[chosen_k]),
        "sample_rows": integer(comparison["train_sample"]), "train_rows": integer(comparison["train_rows"]),
        "train_from": long_date(evaluation["train_from"]), "train_to": long_date(evaluation["train_to"]),
        "test_from": long_date(evaluation["test_from"]), "test_to": long_date(evaluation["test_to"]),
        "test_rows": integer(comparison["test_rows"]),
        "feature_count": str(len(evaluation["importance"])),
        "regression_rows": regression_rows(comparison["regression"]),
        "regression_title": "Los tres modelos más flexibles quedan casi empatados; la diferencia aparece con lluvia",
        "classification_rows": classification_rows(comparison["classification"]),
        "classification_title": "Todos encuentran menos de un tercio de las horas de alta demanda",
        "high_demand": str(comparison["high_demand_threshold"]),
        "high_demand_share": percent(comparison["high_demand_share"], 1),
        "majority_accuracy": percent(majority["accuracy"], 1),
        "choice_text": choice_text(comparison),
        "daily_error_model": percent(all_days["modelo"], 1),
        "daily_error_reference": percent(all_days["habitual ajustado"], 1),
        "rainy_day_error_model": percent(rainy_days["modelo"]),
        "rainy_day_error_reference": percent(rainy_days["habitual ajustado"]),
        "rainy_days_test": str(int(sum(1 for day in evaluation["daily"] if day["rain"] >= 5))),
        "hourly_rain_gain": percent(1 - rain_hours["modelo"] / rain_hours["habitual ajustado"]),
        "hourly_rain_model": decimal(rain_hours["modelo"]),
        "hourly_rain_reference": decimal(rain_hours["habitual ajustado"]),
        "hourly_all_model": decimal(all_hours["modelo"], 3),
        "hourly_all_reference": decimal(all_hours["habitual ajustado"], 3),
        "balance_error": decimal(balance["modelo"]),
        "balance_error_reference": decimal(balance["habitual ajustado"]),
        "scenario_count": integer(len(scenarios["scenarios"])),
        "station_count": str(len(stations)),
        "generated": long_date(datetime.now()),
        "figures_json": json.dumps(figures, ensure_ascii=False, separators=(",", ":")),
        "scenarios_json": json.dumps(scenarios, ensure_ascii=False, separators=(",", ":")),
        "plotly_js": get_plotlyjs(),
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    missing = [key for key in facts if "{{" + key + "}}" not in html]
    for key, value in facts.items():
        html = html.replace("{{" + key + "}}", value)
    # Se revisa solo la parte propia: el código de Plotly incrustado contiene llaves dobles.
    own = html.replace(facts["plotly_js"], "")
    if "{{" in own or missing:
        start = own.find("{{")
        raise SystemExit(f"Plantilla y datos no coinciden. Sin usar: {missing}. Sin completar: {own[start:start + 40]!r}")

    output = REPORTS / "informe.html"
    output.write_text(html, encoding="utf-8")
    print(f"Reporte en {output} ({output.stat().st_size / 1e6:.1f} MB, {time.time() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
