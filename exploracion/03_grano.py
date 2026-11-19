"""Comprueba claves duplicadas del alcance completo, incluso entre bloques.

Ejecutar: python exploracion/03_grano.py
Requiere duckdb. Se usa solo para diagnóstico local; el warehouse del
entregable será Snowflake y las pruebas del pipeline se harán con dbt.
"""

from pathlib import Path

import duckdb


RAIZ = Path(__file__).resolve().parents[1]
conexion = duckdb.connect()  # Base temporal en memoria, sin alterar los CSV.
conexion.execute("SET memory_limit = '512MB'")
# DuckDB puede volcar resultados intermedios a disco si falta memoria.
conexion.execute("SET temp_directory = ?", [str(RAIZ / "exploracion" / ".duckdb_tmp")])
conexion.execute("SET preserve_insertion_order = false")

try:
    # Una vista describe una consulta; no crea otra copia del CSV completo.
    conexion.read_csv(str(RAIZ / "train.csv"), all_varchar=True).create_view("ventas_csv")
    conexion.read_csv(str(RAIZ / "items.csv"), all_varchar=True).create_view("items_csv")
    print("Revisando claves del alcance completo...", flush=True)
    conexion.execute("""
        CREATE TEMP TABLE alcance AS
        SELECT v.id, v.date, v.store_nbr, v.item_nbr
        FROM ventas_csv AS v
        WHERE v.date BETWEEN '2016-08-01' AND '2017-08-15'
          AND v.item_nbr IN (
              SELECT item_nbr FROM items_csv WHERE perishable = '1'
          )
    """)

    print("\nRESUMEN DEL ALCANCE")
    print(conexion.execute("""
        SELECT count(*) AS filas,
               min(date) AS fecha_minima,
               max(date) AS fecha_maxima,
               count(*) FILTER (
                   WHERE id IS NULL OR date IS NULL
                      OR store_nbr IS NULL OR item_nbr IS NULL
               ) AS filas_con_clave_nula,
               count(*) FILTER (
                   WHERE try_cast(date AS DATE) IS NULL
               ) AS fechas_invalidas
        FROM alcance
    """).fetchdf().to_string(index=False))

    # GROUP BY reúne todas las apariciones de una clave, sin importar
    # en qué parte del CSV se encontraban. HAVING conserva las repetidas.
    for nombre, columnas in [
        ("ID", "id"),
        ("Fecha + tienda + producto", "date, store_nbr, item_nbr"),
    ]:
        # Los nombres de columnas son constantes definidos arriba.
        consulta = f"""
            WITH repetidas AS (
                SELECT {columnas}, count(*) AS apariciones
                FROM alcance
                GROUP BY {columnas}
                HAVING count(*) > 1
            )
            SELECT count(*) AS claves_repetidas,
                   coalesce(sum(apariciones), 0)::BIGINT AS filas_involucradas,
                   coalesce(sum(apariciones - 1), 0)::BIGINT AS filas_excedentes
            FROM repetidas
        """
        print(f"\nUnicidad: {nombre}")
        print(conexion.execute(consulta).fetchdf().to_string(index=False))
finally:
    conexion.close()
