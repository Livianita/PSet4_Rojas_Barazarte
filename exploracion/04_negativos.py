"""Diagnostica ventas negativas y cantidades extremas sin modificar ni limpiar las fuentes.

Ejecutar desde Pset2: python exploracion/04_negativos.py
Guarda evidencia pequeña y reproducible en exploracion/resultados/.
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
    conexion.read_csv(str(RAIZ / "stores.csv"), all_varchar=True).create_view("stores_csv")
    print("Revisando cantidades de ventas del alcance...", flush=True)
    conexion.execute("""
        CREATE TEMP TABLE alcance AS
        SELECT v.id, v.date, v.store_nbr, v.item_nbr, v.unit_sales AS unit_sales_original,
               try_cast(v.unit_sales AS DOUBLE) AS unit_sales,
               i.family, s.city, s.state
        FROM ventas_csv AS v
        JOIN items_csv AS i ON v.item_nbr = i.item_nbr
        LEFT JOIN stores_csv AS s ON v.store_nbr = s.store_nbr
        WHERE v.date BETWEEN '2016-08-01' AND '2017-08-15'
          AND i.perishable = '1'
    """)

    resumen = conexion.execute("""
        SELECT count(*) AS filas_alcance,
               count(*) FILTER (WHERE unit_sales IS NULL OR NOT isfinite(unit_sales))
                   AS cantidades_nulas_invalidas_o_no_finitas,
               count(*) FILTER (WHERE unit_sales < 0) AS filas_negativas,
               round(100.0 * count(*) FILTER (WHERE unit_sales < 0) / count(*), 6)
                   AS porcentaje_filas_negativas,
               min(unit_sales) FILTER (WHERE unit_sales < 0) AS negativo_minimo,
               max(unit_sales) FILTER (WHERE unit_sales < 0) AS negativo_maximo,
               median(unit_sales) FILTER (WHERE unit_sales < 0) AS mediana_negativos,
               count(DISTINCT item_nbr) FILTER (WHERE unit_sales < 0) AS productos_con_negativos,
               count(DISTINCT store_nbr) FILTER (WHERE unit_sales < 0) AS tiendas_con_negativos,
               count(DISTINCT date) FILTER (WHERE unit_sales < 0) AS fechas_con_negativos
        FROM alcance
    """).fetchdf()
    print("\nRESUMEN\n" + resumen.to_string(index=False))
    resumen.to_csv(SALIDA / "04_resumen_negativos.csv", index=False)

    negativos = conexion.execute("""
        SELECT * FROM alcance WHERE unit_sales < 0
        ORDER BY unit_sales, date, store_nbr, item_nbr
    """).fetchdf()
    negativos.to_csv(SALIDA / "04_registros_negativos.csv", index=False)
    print("\nDiez registros más negativos:\n" + negativos.head(10).to_string(index=False))

    # El denominador es el total de filas de cada familia, no solo los negativos.
    familias = conexion.execute("""
        SELECT family, count(*) AS filas_familia,
               count(*) FILTER (WHERE unit_sales < 0) AS filas_negativas,
               round(100.0 * count(*) FILTER (WHERE unit_sales < 0) / count(*), 6)
                   AS porcentaje_negativos_en_familia
        FROM alcance GROUP BY family ORDER BY filas_negativas DESC, family
    """).fetchdf()
    familias.to_csv(SALIDA / "04_negativos_por_familia.csv", index=False)
    print("\nNegativos por familia:\n" + familias.to_string(index=False))

    # Extremo positivo: se compara con la mediana del mismo producto y tienda.
    extremos = conexion.execute("""
        SELECT median(unit_sales) AS mediana,
               quantile_cont(unit_sales, 0.999) AS p99_9,
               count(*) FILTER (WHERE unit_sales > 1000) AS filas_sobre_1000,
               max(unit_sales) AS maximo
        FROM alcance
    """).fetchdf()
    print("\nCantidades extremas positivas:\n" + extremos.to_string(index=False))
    extremos.to_csv(SALIDA / "04_resumen_extremos.csv", index=False)
    mayores = conexion.execute("""
        WITH serie AS (
            SELECT store_nbr, item_nbr, median(unit_sales) AS mediana_serie,
                   count(*) AS dias_serie
            FROM alcance GROUP BY store_nbr, item_nbr
        )
        SELECT a.date, a.store_nbr, a.item_nbr, a.family, a.unit_sales,
               s.mediana_serie, s.dias_serie,
               round(a.unit_sales / s.mediana_serie, 1) AS veces_mediana_serie
        FROM alcance AS a JOIN serie AS s USING (store_nbr, item_nbr)
        ORDER BY a.unit_sales DESC LIMIT 10
    """).fetchdf()
    mayores.to_csv(SALIDA / "04_mayores_cantidades.csv", index=False)
    print("\nDiez cantidades más altas:\n" + mayores.to_string(index=False))
    print("\nEvidencia guardada en:", SALIDA)
    print("No se han eliminado ni reemplazado ventas negativas ni extremas.")
finally:
    conexion.close()
