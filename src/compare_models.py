"""Compara distintos algoritmos sobre el mismo problema, para justificar cuál se eligió.

Uso:
    python src/compare_models.py

Hace dos comparaciones con los mismos datos de entrenamiento y los mismos tres meses de prueba:

1. Regresión: predecir cuántas salidas tiene cada estación en cada hora. Es el problema que
   resuelve el modelo del trabajo. Se mide con error absoluto medio, raíz del error cuadrático
   medio, R² y error en los viajes totales del día.
2. Clasificación: predecir si una hora va a ser de alta demanda en una estación (tres o más
   salidas). Es el mismo problema visto como un sí o no, y permite medir exactitud, precisión,
   recall y F1.

Guarda los resultados en reports/models/model_comparison.json.

Todos los algoritmos se entrenan con la misma muestra de filas, porque el random forest y la red
neuronal no terminan en un tiempo razonable con los más de cinco millones de filas completas. El
gradient boosting se entrena además con todas, que es como se usa en el trabajo.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from train_demand import FEATURES, TEST_FROM, add_adjusted_reference, build_table

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "reports" / "models"

TARGET = "departures"
# Una hora de alta demanda es una con tres o más salidas: alrededor de una de cada diez.
HIGH_DEMAND = 3
TRAIN_SAMPLE = 500_000
RANDOM_STATE = 0


def prepared(model):
    """Antepone a un modelo lo que necesita para aceptar estos datos.

    Los modelos lineales y la red neuronal no admiten valores faltantes y funcionan mal con
    variables en escalas distintas, así que se completan los faltantes con la mediana y se
    estandariza.

    :param model: estimador de scikit-learn.
    :returns: el estimador precedido por la imputación y el escalado.
    """
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), model)


def imputed(model):
    """Antepone a un modelo de árboles la imputación de faltantes.

    :param model: estimador de scikit-learn que no admite faltantes.
    :returns: el estimador precedido por la imputación.
    """
    return make_pipeline(SimpleImputer(strategy="median"), model)


def regressors() -> dict:
    """Devuelve los algoritmos de regresión a comparar, con su nombre para mostrar."""
    return {
        "Regresión lineal": prepared(Ridge(alpha=1.0)),
        "Regresión de Poisson": prepared(PoissonRegressor(alpha=1e-4, max_iter=300)),
        "Árbol de decisión": imputed(DecisionTreeRegressor(min_samples_leaf=50, random_state=RANDOM_STATE)),
        "Random forest": imputed(
            RandomForestRegressor(n_estimators=100, min_samples_leaf=20, max_features=0.5, n_jobs=-1,
                                  random_state=RANDOM_STATE)
        ),
        "Red neuronal": prepared(
            MLPRegressor(hidden_layer_sizes=(64, 32), batch_size=1024, early_stopping=True, max_iter=40,
                         random_state=RANDOM_STATE)
        ),
        "Gradient boosting": HistGradientBoostingRegressor(
            loss="poisson", max_iter=200, learning_rate=0.1, max_leaf_nodes=63, random_state=RANDOM_STATE
        ),
    }


def classifiers() -> dict:
    """Devuelve los algoritmos de clasificación a comparar, con su nombre para mostrar."""
    return {
        "Regresión logística": prepared(LogisticRegression(max_iter=500)),
        "Árbol de decisión": imputed(DecisionTreeClassifier(min_samples_leaf=50, random_state=RANDOM_STATE)),
        "Random forest": imputed(
            RandomForestClassifier(n_estimators=100, min_samples_leaf=20, max_features=0.5, n_jobs=-1,
                                   random_state=RANDOM_STATE)
        ),
        "Red neuronal": prepared(
            MLPClassifier(hidden_layer_sizes=(64, 32), batch_size=1024, early_stopping=True, max_iter=40,
                          random_state=RANDOM_STATE)
        ),
        "Gradient boosting": HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.1, max_leaf_nodes=63, random_state=RANDOM_STATE
        ),
    }


def regression_metrics(test: pd.DataFrame, predicted: np.ndarray) -> dict:
    """Mide una predicción de salidas por estación y hora.

    :param test: tabla de prueba, con las salidas reales, la lluvia y la fecha.
    :param predicted: salidas predichas, en el mismo orden.
    :returns: las métricas de regresión.
    """
    actual = test[TARGET].to_numpy()
    predicted = np.clip(predicted, 0, None)
    rainy = (test["precipitation_mm"] >= 0.5).to_numpy()
    daily = pd.DataFrame({"date": test["date"].to_numpy(), "actual": actual, "predicted": predicted})
    daily = daily.groupby("date").sum()
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
        "mae_rain": float(mean_absolute_error(actual[rainy], predicted[rainy])),
        "daily_error": float(((daily["predicted"] - daily["actual"]).abs() / daily["actual"]).mean()),
    }


def classification_metrics(actual: np.ndarray, label: np.ndarray, score: np.ndarray | None) -> dict:
    """Mide una clasificación de horas de alta demanda.

    :param actual: clase real (1 = alta demanda).
    :param label: clase predicha.
    :param score: probabilidad predicha de alta demanda, si el modelo la da.
    :returns: las métricas de clasificación.
    """
    return {
        "accuracy": float(accuracy_score(actual, label)),
        "precision": float(precision_score(actual, label, zero_division=0)),
        "recall": float(recall_score(actual, label)),
        "f1": float(f1_score(actual, label)),
        "auc": float(roc_auc_score(actual, score)) if score is not None else None,
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    table = build_table()
    train = table[table["hour"] < TEST_FROM]
    test = add_adjusted_reference(table[table["hour"] >= TEST_FROM].copy())
    sample = train.sample(TRAIN_SAMPLE, random_state=RANDOM_STATE)
    x_sample = sample[FEATURES].to_numpy(dtype="float32")
    x_test = test[FEATURES].to_numpy(dtype="float32")
    print(f"Entrenamiento: muestra de {len(sample):,} filas de {len(train):,}. Prueba: {len(test):,} filas.")

    # ---- Regresión
    regression = []
    for label, column in (("Uso habitual", "usual_departures"), ("Uso habitual ajustado", "adjusted_departures")):
        regression.append({"model": label, "kind": "referencia", "seconds": 0.0,
                           **regression_metrics(test, test[column].to_numpy())})
    for name, model in regressors().items():
        started = time.time()
        model.fit(x_sample, sample[TARGET].to_numpy())
        seconds = time.time() - started
        regression.append({"model": name, "kind": "muestra", "seconds": seconds,
                           **regression_metrics(test, model.predict(x_test))})
        print(f"regresión  {name:<22} {seconds:6.0f} s  MAE {regression[-1]['mae']:.3f}", flush=True)
    started = time.time()
    full = regressors()["Gradient boosting"].fit(train[FEATURES].to_numpy(dtype="float32"), train[TARGET].to_numpy())
    regression.append({"model": "Gradient boosting (todos los datos)", "kind": "completo",
                       "seconds": time.time() - started, **regression_metrics(test, full.predict(x_test))})

    # ---- Clasificación
    y_sample = (sample[TARGET] >= HIGH_DEMAND).to_numpy().astype(int)
    y_test = (test[TARGET] >= HIGH_DEMAND).to_numpy().astype(int)
    classification = []
    majority = np.zeros_like(y_test)
    classification.append({"model": "Decir siempre que no", "kind": "referencia", "seconds": 0.0,
                           **classification_metrics(y_test, majority, None)})
    usual = test["adjusted_departures"].to_numpy()
    classification.append({"model": "Uso habitual ajustado", "kind": "referencia", "seconds": 0.0,
                           **classification_metrics(y_test, (usual >= HIGH_DEMAND).astype(int), usual)})
    for name, model in classifiers().items():
        started = time.time()
        model.fit(x_sample, y_sample)
        seconds = time.time() - started
        score = model.predict_proba(x_test)[:, 1]
        classification.append({"model": name, "kind": "muestra", "seconds": seconds,
                               **classification_metrics(y_test, (score >= 0.5).astype(int), score)})
        print(f"clasificación {name:<20} {seconds:6.0f} s  F1 {classification[-1]['f1']:.3f}", flush=True)

    result = {
        "train_rows": len(train), "train_sample": len(sample), "test_rows": len(test),
        "test_from": str(test["hour"].min().date()), "test_to": str(test["hour"].max().date()),
        "high_demand_threshold": HIGH_DEMAND, "high_demand_share": float(y_test.mean()),
        "regression": regression, "classification": classification,
    }
    (OUTPUT / "model_comparison.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n== Regresión: salidas por estación y hora")
    print(pd.DataFrame(regression).round(3).to_string(index=False))
    print(f"\n== Clasificación: hora de alta demanda ({HIGH_DEMAND} o más salidas; {y_test.mean():.1%} de las horas)")
    print(pd.DataFrame(classification).round(3).to_string(index=False))
    print(f"\nResultados en {OUTPUT / 'model_comparison.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
