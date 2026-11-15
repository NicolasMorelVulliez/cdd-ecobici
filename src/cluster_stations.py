"""Agrupa las estaciones según cómo se usan (K-means).

Uso:
    python src/cluster_stations.py        # cinco grupos
    python src/cluster_stations.py 3      # otra cantidad

Guarda data/processed/station_clusters.parquet con el grupo de cada estación y el gráfico de los
perfiles en reports/models/.

Por qué K-means: lo que se busca es un puñado de "tipos de estación" que una persona de
operaciones pueda nombrar y recordar. K-means devuelve un perfil promedio por grupo, que se puede
dibujar y explicar.

Por qué cinco grupos: el índice de silueta prefiere tres (recreativas, de origen y de destino).
Con cinco, los grupos de origen y de destino se parten en "leve" y "fuerte", y los fuertes son
justamente las estaciones que hay que reabastecer. Se resigna algo de separación estadística a
cambio de un grupo que sirve para decidir.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
OUTPUT = ROOT / "reports" / "models"

RECENT_FROM = "2025-10-01"
# Con menos movimiento el perfil de una estación es ruido.
MIN_TRIPS_PER_DAY = 5
DEFAULT_GROUPS = 5
CANDIDATE_GROUPS = range(2, 9)
RANDOM_STATE = 0

FEATURES = ["morning_balance", "evening_balance", "weekend_ratio", "night_share"]


def build_features(station_hour: pd.DataFrame, hours: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resume cómo se usa cada estación en cuatro rasgos.

    Se probó agrupar con el perfil completo hora por hora (48 valores) y los grupos salían poco
    separados: muchas horas aportan solo ruido. Estos cuatro rasgos son los que distinguen a una
    estación para la operación:

    - balance de la mañana: llegadas menos salidas de 6 a 10, como proporción del día;
    - balance de la tarde: lo mismo de 16 a 20;
    - uso de fin de semana: viajes por día en fin de semana y feriados sobre los de un día laborable;
    - uso nocturno: proporción de las salidas del día laborable entre las 20 y las 6.

    :param station_hour: salidas y llegadas por estación y hora.
    :param hours: calendario por hora.
    :returns: los rasgos (una fila por estación) y el perfil horario de salidas y llegadas de un
        día laborable, como proporción del día, para graficar.
    """
    recent = station_hour[station_hour["hour"] >= RECENT_FROM].merge(
        hours[["hour", "date", "hour_of_day", "is_workday"]], on="hour"
    )
    workdays = recent[recent["is_workday"]]
    rest = recent[~recent["is_workday"]]
    totals = workdays.groupby(["station_id", "hour_of_day"])[["departures", "arrivals"]].sum()
    departures = totals["departures"].unstack(fill_value=0)
    arrivals = totals["arrivals"].unstack(fill_value=0)
    trips_per_day = departures.sum(axis=1) / workdays["date"].nunique()
    rest_per_day = rest.groupby("station_id")["departures"].sum() / rest["date"].nunique()

    keep = trips_per_day >= MIN_TRIPS_PER_DAY
    departures = departures[keep].div(departures[keep].sum(axis=1), axis=0)
    arrivals = arrivals[keep].div(arrivals[keep].sum(axis=1), axis=0)
    features = pd.DataFrame(
        {
            "trips_per_day": trips_per_day[keep],
            "morning_balance": arrivals.loc[:, 6:10].sum(axis=1) - departures.loc[:, 6:10].sum(axis=1),
            "evening_balance": arrivals.loc[:, 16:20].sum(axis=1) - departures.loc[:, 16:20].sum(axis=1),
            "weekend_ratio": (rest_per_day / trips_per_day).reindex(departures.index).fillna(0),
            "night_share": departures.loc[:, 20:23].sum(axis=1) + departures.loc[:, 0:5].sum(axis=1),
        }
    )
    profile = pd.concat([departures.add_prefix("dep_"), arrivals.add_prefix("arr_")], axis=1)
    return features, profile


def name_group(center: pd.Series) -> str:
    """Le pone nombre a un grupo según su perfil promedio.

    :param center: promedio de los rasgos de las estaciones del grupo.
    :returns: un nombre que describe el rol del grupo.
    """
    if center["weekend_ratio"] > 0.8:
        return "Recreativa"
    if center["morning_balance"] <= -0.08:
        return "Origen fuerte"
    if center["morning_balance"] >= 0.1:
        return "Destino fuerte"
    return "Origen leve" if center["morning_balance"] < 0 else "Destino leve"


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    station_hour = pd.read_parquet(PROCESSED / "station_hour.parquet")
    hours = pd.read_parquet(PROCESSED / "hours.parquet")
    stations = pd.read_parquet(PROCESSED / "stations.parquet").set_index("station_id")

    features, profile = build_features(station_hour, hours)
    # Se estandariza para que los cuatro rasgos pesen lo mismo: están en escalas distintas.
    scaled = StandardScaler().fit_transform(features[FEATURES])

    scores = {}
    for candidate in CANDIDATE_GROUPS:
        labels = KMeans(candidate, n_init=20, random_state=RANDOM_STATE).fit_predict(scaled)
        scores[candidate] = round(float(silhouette_score(scaled, labels)), 3)
    print("Índice de silueta por cantidad de grupos:", scores)

    groups = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GROUPS
    result = features.copy()
    result["cluster"] = KMeans(groups, n_init=20, random_state=RANDOM_STATE).fit_predict(scaled)

    # Los grupos se renumeran del que más pierde bicicletas a la mañana al que más gana, para que
    # el número signifique lo mismo en cada corrida.
    centers = result.groupby("cluster")[FEATURES].mean().sort_values("morning_balance")
    result["cluster"] = result["cluster"].map({old: new for new, old in enumerate(centers.index)})
    centers = centers.reset_index(drop=True)
    names = centers.apply(name_group, axis=1)
    if names.duplicated().any():
        names = names + " " + (names.groupby(names).cumcount() + 1).astype(str)
    result["cluster_name"] = result["cluster"].map(names)
    result = result.join(stations[["name", "zone", "capacity", "subway_distance_m", "train_distance_m"]])

    print(f"\n{len(result)} estaciones en {groups} grupos")
    summary = result.groupby(["cluster", "cluster_name"]).agg(
        stations=("name", "size"),
        trips_per_day=("trips_per_day", "mean"),
        morning_balance=("morning_balance", "mean"),
        evening_balance=("evening_balance", "mean"),
        weekend_ratio=("weekend_ratio", "mean"),
        night_share=("night_share", "mean"),
        subway_m=("subway_distance_m", "median"),
        train_m=("train_distance_m", "median"),
    )
    print(summary.round(2).to_string())
    for (cluster, name), members in result.groupby(["cluster", "cluster_name"]):
        top = members.nlargest(6, "trips_per_day")["name"].tolist()
        zones = members["zone"].value_counts().head(4).to_dict()
        print(f"{cluster} {name}: {top}\n   zonas: {zones}")

    columns = ["cluster", "cluster_name", "trips_per_day"] + FEATURES
    result[columns].reset_index().to_parquet(PROCESSED / "station_clusters.parquet", index=False)

    curves = []
    for kind, prefix in (("Salidas", "dep_"), ("Llegadas", "arr_")):
        mean = profile.filter(like=prefix).set_axis(range(24), axis=1).groupby(result["cluster"]).mean()
        for cluster, row in mean.iterrows():
            size = int((result["cluster"] == cluster).sum())
            for hour, share in row.items():
                curves.append({"Grupo": f"{names[cluster]} ({size})", "Movimiento": kind,
                               "hour": hour, "share": 100 * share})
    figure = px.line(
        pd.DataFrame(curves), x="hour", y="share", color="Movimiento", facet_col="Grupo", facet_col_wrap=3,
        title="Tipos de estación según su día laborable (entre paréntesis, cantidad de estaciones)",
        labels={"hour": "Hora", "share": "% del día"},
    )
    figure.for_each_annotation(lambda annotation: annotation.update(text=annotation.text.split("=")[-1]))
    figure.update_layout(template="plotly_white", font=dict(size=18), title_font=dict(size=24))
    figure.write_html(OUTPUT / "01_grupos_de_estaciones.html", include_plotlyjs="directory")
    print(f"\nGráfico en {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
