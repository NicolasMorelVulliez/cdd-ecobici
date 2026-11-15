"""Entrena los modelos que predicen salidas y llegadas por estación y hora.

Uso:
    python src/cluster_stations.py   # una vez, el grupo de cada estación es una variable del modelo
    python src/train_demand.py

Guarda los modelos en models/ y la tabla de uso habitual en data/processed/usual_profile.parquet.

Por qué este modelo: lo que se predice son conteos chicos con muchos ceros (la mayoría de las
estaciones tiene menos de dos salidas por hora), y el efecto de la lluvia no es el mismo a las 8
que a las 15 ni en una estación de oficinas que en una de parque. Un gradient boosting con pérdida
de Poisson cubre las dos cosas: está hecho para conteos y encuentra solo esas combinaciones. Una
regresión lineal obligaría a escribirlas a mano, y un modelo de series de tiempo por estación
serían más de 400 modelos que no comparten lo aprendido sobre la lluvia.

Contra qué se compara: contra dos referencias que se pueden armar con una planilla. La primera es
el uso habitual de cada estación para ese tipo de día y esa hora. La segunda, más exigente, ajusta
ese uso habitual por el nivel de las últimas cuatro semanas, así que ya tiene en cuenta la época
del año. El modelo solo vale si le gana a la segunda.
"""

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"

# Un año y medio de entrenamiento: alcanza para ver todas las estaciones del año y entra en memoria.
TRAIN_FROM = "2025-01-01"
# Los últimos tres meses con datos se reservan para evaluar: el modelo nunca los ve.
TEST_FROM = "2026-07-01"
# El uso habitual se calcula con el último año de entrenamiento, para que refleje la red actual.
USUAL_FROM = "2025-07-01"

TARGETS = ["departures", "arrivals"]
FEATURES = [
    # Uso habitual de la estación para ese tipo de día y hora, y nivel de las últimas cuatro semanas.
    "usual_departures", "usual_arrivals", "recent_daily_departures",
    # Calendario.
    "hour_of_day", "day_of_week", "month", "is_workday", "is_holiday",
    # Clima.
    "precipitation_mm", "precipitation_prev_3h", "apparent_temperature_c", "wind_speed_kmh", "cloud_cover_pct",
    # Estación.
    "cluster", "capacity", "lon", "lat", "subway_distance_m", "bike_lane_m_within_300m",
]
RANDOM_STATE = 0


def build_table() -> pd.DataFrame:
    """Arma la tabla de entrenamiento: una fila por estación y hora con todas las variables.

    :returns: la tabla desde ``TRAIN_FROM``, con las columnas de ``FEATURES`` y de ``TARGETS``.
    """
    station_hour = pd.read_parquet(PROCESSED / "station_hour.parquet")
    hours = pd.read_parquet(PROCESSED / "hours.parquet")
    stations = pd.read_parquet(PROCESSED / "stations.parquet")
    clusters = pd.read_parquet(PROCESSED / "station_clusters.parquet")[["station_id", "cluster"]]

    # Lluvia de las tres horas anteriores: el piso mojado sigue frenando el uso cuando ya paró.
    hours = hours.sort_values("hour")
    hours["precipitation_prev_3h"] = hours["precipitation_mm"].shift(1).rolling(3, min_periods=1).sum().fillna(0)
    hours["month"] = hours["hour"].dt.month.astype("int8")
    calendar = [
        "hour", "date", "hour_of_day", "day_of_week", "month", "is_workday", "is_holiday",
        "precipitation_mm", "precipitation_prev_3h", "apparent_temperature_c", "wind_speed_kmh", "cloud_cover_pct",
    ]

    # Nivel reciente: promedio de salidas diarias de las cuatro semanas anteriores, sin incluir el
    # día que se predice. Capta que una estación esté creciendo, en baja o recién reabierta.
    daily = station_hour.groupby(["station_id", station_hour["hour"].dt.normalize().rename("date")])["departures"].sum()
    recent = daily.groupby(level="station_id").transform(lambda values: values.shift(1).rolling(28, min_periods=7).mean())
    recent = recent.rename("recent_daily_departures").reset_index()

    table = station_hour[station_hour["hour"] >= TRAIN_FROM].merge(hours[calendar], on="hour")
    table = table.merge(recent, on=["station_id", "date"], how="left")

    # Uso habitual: promedio por estación, tipo de día y hora, calculado solo con datos de entrenamiento.
    window = table[(table["hour"] >= USUAL_FROM) & (table["hour"] < TEST_FROM)]
    usual = window.groupby(["station_id", "is_workday", "hour_of_day"])[TARGETS].mean()
    usual = usual.rename(columns={"departures": "usual_departures", "arrivals": "usual_arrivals"}).reset_index()
    usual.to_parquet(PROCESSED / "usual_profile.parquet", index=False)
    table = table.merge(usual, on=["station_id", "is_workday", "hour_of_day"], how="left")

    station_columns = ["station_id", "capacity", "lon", "lat", "subway_distance_m", "bike_lane_m_within_300m"]
    table = table.merge(stations[station_columns], on="station_id", how="left").merge(clusters, on="station_id", how="left")
    table["capacity"] = table["capacity"].astype("float32")
    # Una estación sin uso habitual es una que abrió después del período de referencia.
    table[["usual_departures", "usual_arrivals"]] = table[["usual_departures", "usual_arrivals"]].fillna(0)
    return table


def add_adjusted_reference(table: pd.DataFrame) -> pd.DataFrame:
    """Agrega la referencia exigente: el uso habitual ajustado por el nivel reciente de la estación.

    :param table: tabla con el uso habitual y el promedio diario de las últimas cuatro semanas.
    :returns: la misma tabla con ``adjusted_departures`` y ``adjusted_arrivals``.
    """
    usual = pd.read_parquet(PROCESSED / "usual_profile.parquet")
    per_day = usual.groupby(["station_id", "is_workday"])["usual_departures"].sum().unstack()
    # Promedio diario habitual de una semana tipo: cinco días laborables y dos que no.
    weekly = ((5 * per_day[True] + 2 * per_day[False]) / 7).rename("usual_daily")
    table = table.join(weekly, on="station_id")
    factor = (table["recent_daily_departures"] / table["usual_daily"]).clip(0, 3).fillna(1)
    for target in TARGETS:
        table[f"adjusted_{target}"] = table[f"usual_{target}"] * factor
    return table


def mean_absolute_error(actual: pd.Series, predicted: pd.Series) -> float:
    """Error absoluto medio.

    :param actual: valores reales.
    :param predicted: valores predichos.
    :returns: el promedio de las diferencias absolutas.
    """
    return float((actual - predicted).abs().mean())


def evaluate(test: pd.DataFrame) -> dict:
    """Compara el modelo contra el uso habitual sobre los meses reservados.

    :param test: tabla de evaluación con las columnas reales, habituales y predichas.
    :returns: los resultados de la evaluación, para el reporte general.
    """
    results = {
        "test_from": f"{test['hour'].min():%Y-%m-%d}", "test_to": f"{test['hour'].max():%Y-%m-%d}",
        "days": int(test["date"].nunique()), "rows": len(test),
    }
    rainy = test["precipitation_mm"] >= 0.5
    print(f"\n== Evaluación sobre {test['date'].nunique()} días ({test['hour'].min():%d/%m/%Y} a {test['hour'].max():%d/%m/%Y})")
    print(f"Horas-estación: {len(test):,}; con lluvia de 0,5 mm o más: {int(rainy.sum()):,}")
    rows = []
    for target in TARGETS:
        for label, mask in (("todas las horas", slice(None)), ("horas con lluvia", rainy)):
            subset = test.loc[mask]
            rows.append(
                {
                    "variable": target,
                    "horas": label,
                    "habitual": mean_absolute_error(subset[target], subset[f"usual_{target}"]),
                    "habitual ajustado": mean_absolute_error(subset[target], subset[f"adjusted_{target}"]),
                    "modelo": mean_absolute_error(subset[target], subset[f"predicted_{target}"]),
                }
            )
    errors = pd.DataFrame(rows)
    errors["mejora sobre ajustado %"] = 100 * (1 - errors["modelo"] / errors["habitual ajustado"])
    print("Error absoluto medio por estación y hora (en viajes):")
    print(errors.round(3).to_string(index=False))
    results["hourly_errors"] = errors.to_dict("records")

    # En términos de operación: viajes totales del día, que definen cuánta logística hace falta.
    daily = test.groupby("date").agg(
        actual=("departures", "sum"), usual=("usual_departures", "sum"),
        adjusted=("adjusted_departures", "sum"), model=("predicted_departures", "sum"),
    )
    rain_by_day = test.drop_duplicates("hour").groupby("date")["precipitation_mm"].sum()
    wet = rain_by_day[rain_by_day >= 5].index
    results["daily"] = daily.assign(rain=rain_by_day).reset_index().assign(
        date=lambda frame: frame["date"].dt.strftime("%Y-%m-%d")).to_dict("records")
    results["daily_errors"] = {}
    for label, days in (("todos los días", daily.index), (f"los {len(wet)} días con 5 mm o más de lluvia", wet)):
        subset = daily.loc[days]
        shares = {
            name: float(((subset[column] - subset["actual"]).abs() / subset["actual"]).mean())
            for name, column in (("habitual", "usual"), ("habitual ajustado", "adjusted"), ("modelo", "model"))
        }
        results["daily_errors"][label] = shares
        print(f"Error en los viajes totales del día, {label}: "
              + ", ".join(f"{name} {share:.1%}" for name, share in shares.items()))

    # Y lo que más importa para redistribuir: el balance de la mañana de cada estación.
    morning = test[test["is_workday"] & test["hour_of_day"].between(6, 10)].copy()
    for kind in ("", "usual_", "adjusted_", "predicted_"):
        morning[f"{kind}net"] = morning[f"{kind}arrivals"] - morning[f"{kind}departures"]
    balance = morning.groupby(["station_id", "date"])[["net", "usual_net", "adjusted_net", "predicted_net"]].sum()
    results["morning_balance_errors"] = {
        name: mean_absolute_error(balance["net"], balance[column])
        for name, column in (("habitual", "usual_net"), ("habitual ajustado", "adjusted_net"), ("modelo", "predicted_net"))
    }
    print(
        "Error en el balance de bicicletas de 6 a 11 por estación y día laborable: "
        f"habitual {mean_absolute_error(balance['net'], balance['usual_net']):.2f}, "
        f"habitual ajustado {mean_absolute_error(balance['net'], balance['adjusted_net']):.2f}, "
        f"modelo {mean_absolute_error(balance['net'], balance['predicted_net']):.2f} bicicletas"
    )
    # El mismo balance sumado por zona, que es la escala a la que se mueve un camión.
    zones = pd.read_parquet(PROCESSED / "stations.parquet")[["station_id", "zone"]].dropna()
    by_zone = balance.reset_index().merge(zones, on="station_id").groupby(["zone", "date"])[
        ["net", "usual_net", "adjusted_net", "predicted_net"]].sum()
    print(
        "Error en el mismo balance sumado por zona: "
        f"habitual {mean_absolute_error(by_zone['net'], by_zone['usual_net']):.2f}, "
        f"habitual ajustado {mean_absolute_error(by_zone['net'], by_zone['adjusted_net']):.2f}, "
        f"modelo {mean_absolute_error(by_zone['net'], by_zone['predicted_net']):.2f} bicicletas "
        f"(balance típico de una zona: {by_zone['net'].abs().mean():.1f})"
    )
    return results


def main() -> int:
    started = time.time()
    MODELS.mkdir(parents=True, exist_ok=True)
    table = build_table()
    train = table[table["hour"] < TEST_FROM]
    test = table[table["hour"] >= TEST_FROM].copy()
    print(f"Entrenamiento: {len(train):,} filas ({train['hour'].min():%d/%m/%Y} a {train['hour'].max():%d/%m/%Y})")

    # En precisión simple la matriz ocupa la mitad de memoria y el modelo no pierde nada.
    train_features = train[FEATURES].to_numpy(dtype="float32")
    test_features = test[FEATURES].to_numpy(dtype="float32")
    for target in TARGETS:
        model = HistGradientBoostingRegressor(
            loss="poisson", max_iter=200, learning_rate=0.1, max_leaf_nodes=63,
            early_stopping=False, random_state=RANDOM_STATE,
        )
        model.fit(train_features, train[target].to_numpy())
        test[f"predicted_{target}"] = model.predict(test_features)
        joblib.dump({"model": model, "features": FEATURES}, MODELS / f"demand_{target}.joblib")
        print(f"Modelo de {target}: {model.n_iter_} iteraciones, {time.time() - started:.0f} s")

        if target == "departures":
            sample = test.sample(100_000, random_state=RANDOM_STATE)
            importance = permutation_importance(
                model, sample[FEATURES].to_numpy(dtype="float32"), sample[target], scoring="neg_mean_absolute_error",
                n_repeats=2, random_state=RANDOM_STATE,
            )
            ranking = pd.Series(importance.importances_mean, index=FEATURES).sort_values(ascending=False)
            print("Variables que más pesan (cuánto empeora el error al desordenarlas):")
            print(ranking.head(10).round(4).to_string())

    results = evaluate(add_adjusted_reference(test))
    results["train_rows"] = len(train)
    results["train_from"] = f"{train['hour'].min():%Y-%m-%d}"
    results["train_to"] = f"{train['hour'].max():%Y-%m-%d}"
    results["importance"] = ranking.round(5).to_dict()
    (MODELS / "evaluation.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nModelos en {MODELS} ({time.time() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
