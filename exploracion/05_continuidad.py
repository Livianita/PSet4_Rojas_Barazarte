"""Mide días sin registro, sin imputar ventas ni asumir surtido disponible.

Ejecutar: python exploracion/05_continuidad.py
Requiere duckdb y pandas. Guarda evidencia en exploracion/resultados/.
"""

from pathlib import Path

import duckdb


RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "exploracion" / "resultados"
SALIDA.mkdir(parents=True, exist_ok=True)

conexion = duckdb.connect()
conexion.execute("SET memory_limit = '512MB'")
conexion.execute("SET temp_directory = ?", [str(RAIZ / 'exploracion' / '.duckdb_tmp')])
conexion.execute("SET preserve_insertion_order = false")

try:
    conexion.read_csv(str(RAIZ / "train.csv"), all_varchar=True).create_view("ventas_csv")
    conexion.read_csv(str(RAIZ / "items.csv"), all_varchar=True).create_view("items_csv")
    print("Revisando presencia de registros por fecha, tienda y producto...", flush=True)
    conexion.execute("""
        CREATE TEMP TABLE alcance AS
        SELECT CAST(v.date AS DATE) AS fecha, v.store_nbr, v.item_nbr
        FROM ventas_csv AS v
        WHERE v.date BETWEEN '2016-08-01' AND '2017-08-15'
          AND v.item_nbr IN (SELECT item_nbr FROM items_csv WHERE perishable = '1')
    """)

    # DISTINCT impide contar dos veces un día si las fuentes cambian.
    conexion.execute("""
        CREATE TEMP TABLE series AS
        WITH limites AS (
            SELECT store_nbr, item_nbr, min(fecha) AS primera_fecha,
                   max(fecha) AS ultima_fecha, count(DISTINCT fecha) AS dias_con_registro
            FROM alcance GROUP BY store_nbr, item_nbr
        ), intervalos AS (
            SELECT *, date_diff('day', primera_fecha, ultima_fecha) + 1 AS dias_entre_extremos,
                   date_diff('day', DATE '2016-08-01', primera_fecha) AS dias_antes,
                   date_diff('day', ultima_fecha, DATE '2017-08-15') AS dias_despues
            FROM limites
        )
        SELECT *, dias_entre_extremos - dias_con_registro AS dias_sin_registro_internos
        FROM intervalos
    """)

    resumen = conexion.execute("""
        SELECT count(*) AS series_observadas,
               380 AS dias_del_periodo,
               sum(dias_con_registro)::BIGINT AS observaciones,
               count(*) FILTER (WHERE dias_sin_registro_internos > 0) AS series_con_huecos_internos,
               sum(dias_sin_registro_internos)::BIGINT AS dias_serie_sin_registro_internos,
               sum(dias_antes)::BIGINT AS dias_serie_antes_del_primer_registro,
               sum(dias_despues)::BIGINT AS dias_serie_despues_del_ultimo_registro,
               median(dias_con_registro) AS mediana_dias_observados_por_serie
        FROM series
    """).fetchdf()
    # Comprobación aritmética: cada serie observada tiene 380 días posibles
    # en el calendario, sin que ello implique que el producto estaba disponible.
    fila = resumen.iloc[0]
    total_partes = sum(int(fila[c]) for c in [
        'observaciones', 'dias_serie_sin_registro_internos',
        'dias_serie_antes_del_primer_registro', 'dias_serie_despues_del_ultimo_registro',
    ])
    if total_partes != int(fila['series_observadas']) * 380:
        raise ValueError('La partición de días por serie no coincide con el calendario.')

    # LAG compara cada fecha con la observación anterior de la misma serie.
    conexion.execute("""
        CREATE TEMP TABLE todos_huecos AS
        WITH fechas_unicas AS (
            SELECT DISTINCT store_nbr, item_nbr, fecha FROM alcance
        ), anteriores AS (
            SELECT *, lag(fecha) OVER (
                PARTITION BY store_nbr, item_nbr ORDER BY fecha
            ) AS fecha_anterior FROM fechas_unicas
        )
        SELECT store_nbr, item_nbr, fecha_anterior, fecha,
               date_diff('day', fecha_anterior, fecha) - 1 AS dias_sin_registro
        FROM anteriores
        WHERE date_diff('day', fecha_anterior, fecha) > 1
    """)
    huecos = conexion.execute("""
        SELECT * FROM todos_huecos
        ORDER BY dias_sin_registro DESC, store_nbr, item_nbr, fecha
        LIMIT 20
    """).fetchdf()

    # Cada intervalo pertenece a una sola categoría. Una serie puede tener
    # varios intervalos, incluso de categorías diferentes.
    distribucion = conexion.execute("""
        WITH clasificados AS (
            SELECT *, CASE
                WHEN dias_sin_registro <= 7 THEN 1
                WHEN dias_sin_registro <= 30 THEN 2
                WHEN dias_sin_registro <= 90 THEN 3
                WHEN dias_sin_registro <= 180 THEN 4
                ELSE 5 END AS grupo
            FROM todos_huecos
        )
        SELECT CASE grupo WHEN 1 THEN '1-7 días' WHEN 2 THEN '8-30 días'
                   WHEN 3 THEN '31-90 días' WHEN 4 THEN '91-180 días'
                   ELSE '181 días o más' END AS duracion,
               count(*) AS intervalos,
               count(DISTINCT (store_nbr, item_nbr)) AS series_afectadas,
               sum(dias_sin_registro)::BIGINT AS dias_serie_sin_registro
        FROM clasificados GROUP BY grupo ORDER BY grupo
    """).fetchdf()

    # Umbrales acumulativos: una serie con un hueco de 200 días también
    # cuenta en los umbrales de 30 y 90; no se deben sumar estas filas.
    umbrales = conexion.execute("""
        WITH maximos AS (
            SELECT store_nbr, item_nbr, max(dias_sin_registro) AS hueco_maximo
            FROM todos_huecos GROUP BY store_nbr, item_nbr
        )
        SELECT umbral AS hueco_de_al_menos_dias,
               count(*) FILTER (WHERE hueco_maximo >= umbral) AS series_afectadas,
               round(100.0 * count(*) FILTER (WHERE hueco_maximo >= umbral)
                   / (SELECT count(*) FROM series), 2) AS porcentaje_series_observadas
        FROM maximos CROSS JOIN (VALUES (30), (90), (180), (300)) AS limites(umbral)
        GROUP BY umbral ORDER BY umbral
    """).fetchdf()
    if int(distribucion['dias_serie_sin_registro'].sum()) != int(fila['dias_serie_sin_registro_internos']):
        raise ValueError('La suma de los intervalos no coincide con los huecos por serie.')

    detalle = conexion.execute("SELECT * FROM series ORDER BY store_nbr, item_nbr").fetchdf()
    resumen.to_csv(SALIDA / '05_resumen_continuidad.csv', index=False)
    detalle.to_csv(SALIDA / '05_continuidad_por_serie.csv', index=False)
    huecos.to_csv(SALIDA / '05_huecos_mas_largos.csv', index=False)
    distribucion.to_csv(SALIDA / '05_distribucion_huecos.csv', index=False)
    umbrales.to_csv(SALIDA / '05_series_con_huecos_largos.csv', index=False)
    print('\nRESUMEN\n' + resumen.to_string(index=False))
    print('\nDiez huecos internos más largos:\n' + huecos.head(10).to_string(index=False))
    print('\nComprobación de días por serie: correcta.')
    print('\nDistribución de todos los huecos:\n' + distribucion.to_string(index=False))
    print('\nSeries por umbral acumulativo:\n' + umbrales.to_string(index=False))
    print('Los días sin registro NO se han convertido en ventas cero.')
finally:
    conexion.close()
