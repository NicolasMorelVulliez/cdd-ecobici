# Estaciones actuales de Ecobici

**Origen:** https://buenosaires.publicbikesystem.net/customer/gbfs/v2/gbfs.json

**Publica:** el operador del sistema BA Ecobici, en formato GBFS (estándar abierto para sistemas de bicicletas compartidas). No pide clave.

**Descargado:** 2026-11-14, de
https://buenosaires.publicbikesystem.net/customer/gbfs/v2/pt/station_information

## Archivos

| Archivo | Contenido |
|---|---|
| `station_information.json` | 392 estaciones vigentes al día de la descarga: identificador, nombre, dirección, latitud, longitud, **capacidad** (anclajes) y grupo o barrio. |

## A tener en cuenta

- `station_id` es el mismo identificador que traen los recorridos (sin el sufijo `BAEcobici`). Verificado contra los viajes de 2026: 387 de 407 estaciones coinciden en identificador y ubicación, y cubren el 97,4% de los viajes.
- Es una foto del día de la descarga. Las estaciones dadas de baja antes no figuran, y la capacidad puede haber cambiado en el tiempo. Para 2019 hay otra foto en `../conicet/estaciones_2019.xlsx`.
- El mismo índice ofrece `station_status` (bicicletas y anclajes disponibles en este momento). No tiene historial: para usarlo hay que capturarlo periódicamente.
