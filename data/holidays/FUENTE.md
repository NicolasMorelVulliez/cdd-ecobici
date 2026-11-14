# Feriados nacionales de Argentina 2019-2026

**Origen:** se combinaron tres fuentes, una por tramo de años (la columna `fuente` del CSV dice de cuál salió cada fila):

| `fuente` | Años | Origen |
|---|---|---|
| `nolaborables` | 2019, 2020 y la fila 2022-06-17 | https://github.com/pjnovas/nolaborables, archivos `lib/data/holidays/AAAA.json` (fechas) y `lib/data/holidays/ref.json` (nombre y tipo de cada feriado) |
| `argentinadatos` | 2021 a 2024 | https://api.argentinadatos.com/v1/feriados/AAAA (documentación en https://argentinadatos.com) |
| `argentina.gob.ar` | 2025 y 2026 | Calendario oficial en https://www.argentina.gob.ar/feriados, que se carga desde https://www.argentina.gob.ar/sites/default/files/holidays-AAAA-es.json |

**Publica:**
- `nolaborables`: proyecto comunitario de código abierto (usuario `pjnovas` en GitHub). Su README anuncia la baja del servicio y no tiene datos posteriores a 2024.
- `argentinadatos`: ArgentinaDatos, API pública y gratuita de un proyecto comunitario de código abierto (repositorio `enzonotario/esjs-argentina-datos-api`). No tiene 2019 ni 2020 (responde 404).
- `argentina.gob.ar`: Gobierno nacional. El JSON declara como editor al Ministerio del Interior; la página está dentro de Jefatura de Gabinete de Ministros. Solo publica los dos últimos años (2025 y 2026); las páginas de años anteriores ya no están en línea.

**Licencia:**
- `nolaborables`: BSD 2-Clause (archivo `LICENSE` del repositorio).
- `argentinadatos`: MIT, según el pie de argentinadatos.com.
- `argentina.gob.ar`: CC BY 4.0, según el pie del sitio (hay que citar la fuente).

**Descargado:** 2026-11-14.

## Archivos

| Archivo | Contenido |
|---|---|
| `feriados_2019_2026.csv` | 156 días feriados del 2019-01-01 al 2026-12-25, una fila por día, ordenados por fecha. Columnas: `fecha` (AAAA-MM-DD), `tipo` (tal como lo da la fuente), `nombre` y `fuente`. Codificación UTF-8. Por año: 2019: 19, 2020: 19, 2021: 18, 2022: 22, 2023: 19, 2024: 19, 2025: 19, 2026: 21. |

## A tener en cuenta

- Están los feriados inamovibles, trasladables, los días con fines turísticos (puentes) y los feriados extraordinarios. Quedan afuera los días no laborables optativos (Jueves Santo, festividades judías e islámicas y el 24 de abril), que no cortan la actividad general.
- `tipo` respeta el vocabulario de cada fuente: `puente` (nolaborables y ArgentinaDatos) y `turistico` (argentina.gob.ar) son lo mismo, los días con fines turísticos del artículo 7 de la Ley 27.399. Su alcance legal cambió: en 2019 fueron días no laborables (Decreto 923/2017), en 2020 y 2022 feriados (Decretos 717/2019 y 789/2021) y en 2025 y 2026 el calendario oficial los publica como días no laborables. Para 2021, 2023 y 2024 no se verificó el texto del decreto. En un día no laborable el empleador privado decide si se trabaja, así que la demanda puede quedar entre la de un día hábil y la de un feriado.
- Los feriados que caen sábado o domingo figuran igual en su fecha. No suman un día hábil perdido.
- Hay un solo caso de dos feriados el mismo día: el 2021-04-02 coincidieron Viernes Santo y Malvinas. ArgentinaDatos solo lista Viernes Santo.
- **2020:** el feriado de Malvinas se pasó del 2 al 31 de marzo (DNU 297/2020, art. 7). El lunes 30 de marzo no fue feriado: fue asueto solo para la Administración Pública Nacional (art. 9). Desde el 20 de marzo regía el aislamiento obligatorio, así que en 2020 la demanda depende mucho más de la cuarentena que de los feriados.
- **2022:** hubo tres feriados nacionales extraordinarios: el 18/5 por el censo (Decreto 42/2022), el 2/9 tras el atentado contra la vicepresidenta (DNU 573/2022) y el 20/12 por los festejos del Mundial (DNU 842/2022). En el CSV los dos últimos se llaman como en ArgentinaDatos: "Decreto de Necesidad y Urgencia".
- **2022-06-17:** ArgentinaDatos lo marca como puente, pero el Decreto 789/2021 fija los puentes de 2022 el 7/10, el 21/11 y el 9/12. Ese viernes fue el feriado de Güemes, que no se trasladó porque el lunes 20 ya era feriado. Por eso esa fila sale de nolaborables.
- **2025-10-10:** el Día del Respeto a la Diversidad Cultural se pasó del domingo 12 al viernes 10 (Resolución 139/2025 de Jefatura de Gabinete). ArgentinaDatos marca el 10 como puente y deja también el 12. Para 2025 se usó el calendario oficial.
- **2026-11:** el 9/11 fue feriado nacional por la visita del papa León XIV (Decreto 1103/2026). El 10/11 (`tipo` = `especial`) fue feriado solo en Córdoba y la Ciudad de Buenos Aires: se incluye porque Ecobici funciona en la Ciudad. El 11/11, feriado solo en la provincia de Buenos Aires, quedó afuera.
- El JSON oficial de 2026 repite el 1/1/2026 y trae también el 1/1/2027: se dejó una sola fila y se descartó la de 2027.
- Validación cruzada: 2021 a 2024 coinciden día por día entre ArgentinaDatos y nolaborables (la única diferencia de tipo es el 2022-06-17, y nolaborables no tiene los tres feriados extraordinarios de 2022). 2025 y 2026 coinciden entre el calendario oficial y ArgentinaDatos, salvo los casos de 2025-10-10 y 2026-11-10/11 de arriba. Los puentes de 2019, 2020 y 2022, el traslado de 2020, los feriados extraordinarios de 2022 y el traslado del 12/10/2025 se confirmaron contra el texto de las normas en el Boletín Oficial (https://www.boletinoficial.gob.ar). El Decreto 1103/2026 no se leyó en el Boletín Oficial: su contenido sale del propio JSON oficial.
- Como control también se comparó contra Nager.Date (https://date.nager.at). No se usó como fuente porque no trae puentes ni feriados extraordinarios, pone Malvinas 2020 el 2 de abril (contradice el DNU 297/2020), pone Güemes 2022 el lunes 20/6 en vez del viernes 17 y deja el 12/10/2025 en domingo. Fuera de eso, coincide con el CSV en todos los años.
