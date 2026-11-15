# Ecobici: cuánta redistribución de bicicletas hace falta mañana

Trabajo Práctico Obligatorio de Ciencia de Datos (UADE).

Analiza los viajes del sistema de bicicletas públicas de la Ciudad de Buenos Aires, cruzados con el clima, para
planificar el día anterior con cuántas bicicletas conviene dejar cada estación.

## Hipótesis

> Cuánta redistribución hace falta mañana es predecible con el clima, y dónde hace falta lo dice el tipo de estación;
> juntos permiten dimensionar la logística el día anterior.

- **Para quién:** la gerencia de operaciones del sistema.
- **Valor:** las estaciones se dejan preparadas según lo que se espera para el día siguiente, y los días de lluvia no se
  gasta logística en una demanda que no va a estar.

## Qué incluye

| Entregable | Dónde está |
|---|---|
| Reporte general, con comparación de algoritmos y una predicción interactiva | `reports/informe.html` |
| Aplicación con el plan de redistribución para un día | `src/app.py` |
| Análisis exploratorio | `src/eda.py` y `reports/eda/` |
| Tipos de estación (K-means) | `src/cluster_stations.py` |
| Modelo de demanda (gradient boosting) | `src/train_demand.py` |
| Comparación de algoritmos | `src/compare_models.py` |

## Cómo ejecutarlo

Hace falta Python 3.12 o posterior (se probó con 3.14 en Windows) y unos 12 GB de disco para los recorridos
descomprimidos.

### 1. Descomprimir los recorridos

Los CSV de recorridos pesan 9 GB y no entran en el repositorio. Están comprimidos en nueve volúmenes en `data/trips/`
(`trips.part001.rar` a `trips.part009.rar`).

Hay que descomprimirlos **en la misma carpeta `data/trips/`**, abriendo solo el primer volumen; los demás se leen solos.

- Con WinRAR o 7-Zip: clic derecho sobre `trips.part001.rar` y «Extraer aquí».
- Por línea de comandos, con WinRAR instalado:

  ```
  "C:\Program Files\WinRAR\UnRAR.exe" x data\trips\trips.part001.rar data\trips\
  ```

Al terminar tienen que quedar 17 archivos, de `trips_2010.csv` a `trips_2026.csv`. El trabajo usa los de 2019 en
adelante. El resto de los datos (clima, feriados, estaciones, ciclovías y transporte) ya está en el repositorio y no
hay que descomprimir nada más.

### 2. Instalar las librerías

Desde la raíz del repositorio, en un entorno virtual:

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

En Linux o macOS el entorno se activa con `source .venv/bin/activate`.

### 3. Ejecutar todo

```
python src/run_all.py
```

Hace todos los pasos en orden y tarda unos 10 minutos:

1. Baja el clima horario de Open-Meteo.
2. Unifica los recorridos y arma las tablas de trabajo.
3. Hace el análisis exploratorio.
4. Agrupa las estaciones en tipos.
5. Entrena los modelos de demanda.
6. Compara algoritmos.
7. Arma el reporte general.

Antes de empezar revisa que estén las librerías y los recorridos descomprimidos, y si falta algo dice qué hacer. Si un
paso falla, se detiene ahí.

| Opción | Qué hace |
|---|---|
| `--offline` | No vuelve a bajar el clima; usa el archivo que ya está en el repositorio |
| `--app` | Abre la aplicación al terminar |

### 4. Ver los resultados

- **Reporte general:** abrir `reports/informe.html` en el navegador. Es un único archivo que funciona sin conexión.
  Ya está en el repositorio, así que se puede ver sin ejecutar nada; al correr el trabajo se vuelve a generar.
- **Aplicación:**

  ```
  streamlit run src/app.py
  ```

  Se elige el día y el clima previsto, y muestra con cuántas bicicletas dejar cada estación, en un mapa y en una
  lista descargable. También funciona sin conexión.

Cada script se puede correr por separado (`python src/eda.py`, por ejemplo), siempre después de
`src/build_dataset.py`.

## Estructura

```
data/
  trips/        recorridos por año (comprimidos) 
  users/        usuarios por año
  weather/      clima horario
  holidays/     feriados
  stations/     estaciones actuales y su capacidad
  conicet/      estaciones y ciclovías de 2019
  road/         red de ciclovías
  transit/      estaciones de subte, tren, premetro y Metrobus
  processed/    tablas de trabajo (se generan)
src/            código
models/         modelos entrenados (se generan)
reports/        reporte general y gráficos (están en el repositorio y se rehacen al ejecutar)
```

Cada carpeta de `data/` tiene un `FUENTE.md` con el origen de los datos, su licencia y las particularidades del
formato.

## Código

| Script | Qué hace |
|---|---|
| `run_all.py` | Ejecuta todo en un solo paso |
| `download_weather.py` | Baja el clima horario |
| `build_dataset.py` | Unifica los recorridos de 2022 a 2026 y arma las tablas de viajes, estaciones, horas y estación por hora |
| `eda.py` | Análisis exploratorio y sus gráficos |
| `cluster_stations.py` | Agrupa las estaciones en cinco tipos con K-means |
| `train_demand.py` | Entrena y evalúa los modelos de salidas y llegadas por estación y hora |
| `compare_models.py` | Compara regresión lineal, árbol de decisión, random forest, red neuronal y gradient boosting |
| `forecast.py` | Predice un día completo y calcula el stock recomendado de cada estación |
| `app.py` | Aplicación en Streamlit |
| `build_report.py` | Arma el reporte general a partir de `report_template.html` |
| `capture_station_status.py` | Captura el estado en vivo de las estaciones. No se usa en el trabajo |

## Datos

Los viajes llegan hasta el 30 de septiembre de 2026, que es lo último que había publicado el portal; el clima y el
calendario llegan hasta el 31 de octubre de 2026.

| Fuente | Origen | Licencia |
|---|---|---|
| Recorridos y usuarios de Ecobici | [Buenos Aires Data](https://data.buenosaires.gob.ar/dataset/bicicletas-publicas) | CC BY 2.5 AR |
| Ciclovías | [Buenos Aires Data](https://data.buenosaires.gob.ar/dataset/ciclovias) | CC BY 2.5 AR |
| Subte, tren, premetro y Metrobus | Buenos Aires Data | CC BY 2.5 AR |
| Clima horario | [Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) | CC BY 4.0 |
| Estaciones actuales y capacidad | [Feed GBFS de BA Ecobici](https://buenosaires.publicbikesystem.net/customer/gbfs/v2/gbfs.json) | — |
| Ecobici 2010–2019 | [CONICET Digital](https://ri.conicet.gov.ar/items/0d38d154-0a4c-4d9b-8863-05cbffc2134c), Gutiérrez y Mené | Ver `data/conicet/FUENTE.md` |
| Feriados | argentina.gob.ar, ArgentinaDatos y nolaborables | Ver `data/holidays/FUENTE.md` |
