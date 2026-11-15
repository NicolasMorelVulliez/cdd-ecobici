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

# Configuración de Plotly para los mapas (el tercer argumento de Plotly.newPlot). Los ejes cartesianos
# no acercan con la rueda salvo que se pida; la barra queda siempre visible porque es la única forma
# de acercar en una pantalla táctil, y el doble clic vuelve siempre al encuadre inicial.
CONFIG = dict(scrollZoom=True, displayModeBar=True, displaylogo=False, doubleClick="reset", responsive=True)

# Botones que no sirven en un mapa: el ajuste automático lo encuadra según las estaciones y deforma
# el encuadre inicial, los de selección no hacen nada en estos gráficos y el de compartir manda los
# datos a un servicio externo.
_REMOVED_BUTTONS = ["autoScale2d", "zoom2d", "pan2d", "select2d", "lasso2d", "toImage", "sendChartToCloud"]

ZOOM_SCRIPT = Path(__file__).resolve().parent / "map_zoom.js"


def zoom_script() -> str:
    """Devuelve el código JavaScript que define ``enableMapZoom(gd)``.

    Hay que llamarla después de dibujar el mapa con ``CONFIG``: hace que la rueda acerque recién al
    hacer clic en el mapa, para no atrapar el desplazamiento de la página, y pasa la barra a español.
    """
    return ZOOM_SCRIPT.read_text(encoding="utf-8")


def post_script() -> str:
    """Devuelve el código para el parámetro ``post_script`` de ``write_html``."""
    return zoom_script() + "\nenableMapZoom(document.getElementById('{plot_id}'));"


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
    diferencia es de a lo sumo un píxel de la imagen, que no se nota ni acercando. Al acercar se
    mantiene la proporción porque el eje vertical está atado al horizontal.

    Para que se pueda acercar hay que dibujarlo con ``CONFIG`` (y, en una página HTML propia,
    llamar a ``enableMapZoom`` de ``zoom_script()``).

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
        modebar=dict(remove=_REMOVED_BUTTONS, orientation="v", bgcolor="rgba(255, 255, 255, 0.85)"),
        # Con un valor fijo, si una página vuelve a dibujar el mapa con Plotly.react (por ejemplo al
        # cambiar un control) se conserva el acercamiento que eligió quien lo mira. Streamlit, en
        # cambio, arma un gráfico nuevo y vuelve al encuadre inicial.
        uirevision="map",
    )
