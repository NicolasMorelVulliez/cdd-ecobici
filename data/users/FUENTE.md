# Usuarios de Ecobici

**Origen:** https://data.buenosaires.gob.ar/dataset/bicicletas-publicas

**Publica:** Gobierno de la Ciudad de Buenos Aires, portal Buenos Aires Data.

**Licencia:** CC BY 2.5 AR (hay que citar la fuente).

**Fuente primaria:** Secretaría de Transporte y Obras Públicas.

**Actualización:** mensual. El portal publica un recurso "Usuarios Ecobici" por año, de 2015 a 2026.

## Archivos

Un CSV por año, de `usuarios_ecobici_2015.csv` a `usuarios_ecobici_2026.csv`. Cada fila es un usuario dado de alta ese año: identificador, género, edad, fecha y hora de alta.

## A tener en cuenta

- El nombre de la columna del identificador cambia (`id_usuario` o `ID Cliente`), igual que el formato de fecha y los valores de género (`M/F` o `MALE/FEMALE/OTHER`).
- Los archivos recientes agregan una columna que indica si el usuario cargó DNI.
