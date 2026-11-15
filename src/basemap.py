"""Mapa base de la Ciudad para dibujar debajo de las estaciones.

El mapa es una imagen guardada en data/basemap/ (la baja download_basemap.py), así que los mapas
del trabajo se ven sin conexión y sin WebGL. Se usa como fondo de un gráfico común de puntos, con
la longitud en el eje horizontal y la latitud en el vertical.
"""

import base64
import json
import math
from functools import lru_cache
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent / "data" / "basemap"

# Encuadre por defecto: toda la Ciudad, con un margen alrededor de las estaciones.
LON_RANGE = (-58.54, -58.34)
LAT_RANGE = (-34.70, -34.525)

ATTRIBUTION = "Mapa base: © colaboradores de OpenStreetMap"


@lru_cache(maxsize=1)
def _image() -> tuple[str, dict]:
    """Lee la imagen del mapa y sus límites.

    :returns: la imagen como URI de datos y sus límites en longitud y latitud.
    """
    encoded = base64.b64encode((FOLDER / "caba.jpg").read_bytes()).decode("ascii")
    limits = json.loads((FOLDER / "caba.json").read_text(encoding="utf-8"))
    return f"data:image/jpeg;base64,{encoded}", limits


def layout(lon_range: tuple = LON_RANGE, lat_range: tuple = LAT_RANGE) -> dict:
    """Devuelve el diseño de un gráfico de Plotly con el mapa de fondo.

    Los ejes quedan ocultos y con la proporción correcta: a la latitud de Buenos Aires un grado de
    longitud mide menos que uno de latitud, así que el eje vertical se estira en esa proporción.
    La imagen está en proyección Mercator y los ejes son lineales, pero en una ciudad de 20 km la
    diferencia es de centésimas de píxel.

    :param lon_range: longitudes mínima y máxima a mostrar.
    :param lat_range: latitudes mínima y máxima a mostrar.
    :returns: un diccionario para pasar a ``figure.update_layout``.
    """
    source, limits = _image()
    middle = math.radians(sum(lat_range) / 2)
    return dict(
        images=[dict(
            source=source, xref="x", yref="y", x=limits["west"], y=limits["north"],
            sizex=limits["east"] - limits["west"], sizey=limits["north"] - limits["south"],
            xanchor="left", yanchor="top", sizing="stretch", layer="below",
        )],
        xaxis=dict(range=list(lon_range), visible=False, constrain="domain", fixedrange=False),
        yaxis=dict(range=list(lat_range), visible=False, scaleanchor="x", scaleratio=1 / math.cos(middle),
                   constrain="domain"),
        plot_bgcolor="white", dragmode="pan",
    )
