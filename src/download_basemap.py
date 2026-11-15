"""Descarga un mapa base de la Ciudad de Buenos Aires y lo guarda como una sola imagen.

Uso:
    python src/download_basemap.py

Guarda data/basemap/caba.jpg y data/basemap/caba.json (los límites de la imagen en longitud y
latitud). El reporte incrusta esa imagen debajo de las estaciones, así el mapa se ve sin conexión
y sin depender de WebGL.

El mapa base es el de OpenStreetMap. Se descarga una sola vez (son 42 teselas) y se aclara y se
pasa a grises, para que las calles sirvan de referencia sin competir con los datos.
"""

import io
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
# OpenStreetMap pide que los clientes automáticos se identifiquen.
USER_AGENT = "tp-ciencia-de-datos/1.0 (descarga unica de un mapa base)"
# Cuánto se aclara el mapa: 0 lo deja igual, 1 lo deja blanco.
FADE = 0.45
ZOOM = 13
TILE_SIZE = 256
# Rectángulo que contiene a la Ciudad (oeste, sur, este, norte).
BOUNDS = (-58.54, -34.71, -58.33, -34.52)

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "basemap"


def tile_of(lon: float, lat: float) -> tuple[float, float]:
    """Convierte longitud y latitud a coordenadas de tesela (con decimales) en proyección Mercator.

    :param lon: longitud en grados.
    :param lat: latitud en grados.
    :returns: posición x e y en la grilla de teselas del nivel de zoom.
    """
    scale = 2 ** ZOOM
    x = (lon + 180) / 360 * scale
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    return x, y


def corner_of(x: int, y: int) -> tuple[float, float]:
    """Devuelve la longitud y latitud de la esquina superior izquierda de una tesela.

    :param x: columna de la tesela.
    :param y: fila de la tesela.
    :returns: longitud y latitud en grados.
    """
    scale = 2 ** ZOOM
    lon = x / scale * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
    return lon, lat


def main() -> int:
    west, south, east, north = BOUNDS
    left, top = (int(value) for value in tile_of(west, north))
    right, bottom = (int(value) for value in tile_of(east, south))
    columns, rows = right - left + 1, bottom - top + 1
    image = Image.new("RGB", (columns * TILE_SIZE, rows * TILE_SIZE))
    print(f"{columns * rows} teselas ({columns} x {rows}) en zoom {ZOOM}")
    for x in range(left, right + 1):
        for y in range(top, bottom + 1):
            request = urllib.request.Request(TILE_URL.format(zoom=ZOOM, x=x, y=y), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                tile = Image.open(io.BytesIO(response.read())).convert("RGB")
            image.paste(tile, ((x - left) * TILE_SIZE, (y - top) * TILE_SIZE))
            time.sleep(0.2)  # sin apuro: es un servicio gratuito sostenido por donaciones

    # En grises y aclarado: el mapa base es contexto, no dato.
    gray = image.convert("L")
    image = Image.blend(gray, Image.new("L", gray.size, 255), FADE)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    # JPEG en grises: pesa la cuarta parte que un PNG y en un mapa de fondo no se nota la diferencia.
    image.save(OUTPUT / "caba.jpg", quality=80, optimize=True)
    image_west, image_north = corner_of(left, top)
    image_east, image_south = corner_of(right + 1, bottom + 1)
    limits = {"west": image_west, "south": image_south, "east": image_east, "north": image_north,
              "width": image.width, "height": image.height, "zoom": ZOOM}
    (OUTPUT / "caba.json").write_text(json.dumps(limits, indent=2), encoding="utf-8")
    print(f"{image.width} x {image.height} px -> {OUTPUT / 'caba.jpg'} ({(OUTPUT / 'caba.jpg').stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
