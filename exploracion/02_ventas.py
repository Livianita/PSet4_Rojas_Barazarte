"""Diagnóstico del alcance de PSET1, leyendo train.csv por bloques.

Ejecutar desde Pset2: python exploracion/02_ventas.py
No modifica los datos ni aplica decisiones de limpieza.
"""

from pathlib import Path

import pandas as pd


CARPETA_DATOS = Path(__file__).resolve().parents[1]
FECHA_INICIO = "2016-08-01"
FECHA_FIN = "2017-08-15"
FILAS_POR_BLOQUE = 1_000_000

items = pd.read_csv(CARPETA_DATOS / "items.csv")
stores = pd.read_csv(CARPETA_DATOS / "stores.csv")
productos_catalogo = set(items["item_nbr"])
productos_perecederos = set(items.loc[items["perishable"] == 1, "item_nbr"])
tiendas_catalogo = set(stores["store_nbr"])

filas_leidas = 0
filas_periodo = 0
filas_alcance = 0
negativas = 0
ceros = 0
promociones_nulas = 0
productos_sin_catalogo = 0
tiendas_sin_catalogo = 0
productos_observados = set()
tiendas_observadas = set()
conteos_por_tienda = pd.Series(dtype="int64")
ejemplo = None

# chunksize devuelve bloques sucesivos, en lugar de una única tabla de 5 GB.
# Las fechas ISO YYYY-MM-DD permiten comparar su orden como texto.
bloques = pd.read_csv(
    CARPETA_DATOS / "train.csv",
    chunksize=FILAS_POR_BLOQUE,
    dtype={"date": "string", "onpromotion": "string"},
)

for numero, bloque in enumerate(bloques, start=1):
    filas_leidas += len(bloque)
    periodo = bloque.loc[bloque["date"].between(FECHA_INICIO, FECHA_FIN)]
    filas_periodo += len(periodo)

    # Antes de filtrar productos, comprobamos referencias desconocidas.
    productos_sin_catalogo += int((~periodo["item_nbr"].isin(productos_catalogo)).sum())
    tiendas_sin_catalogo += int((~periodo["store_nbr"].isin(tiendas_catalogo)).sum())

    ventas = periodo.loc[periodo["item_nbr"].isin(productos_perecederos)]
    filas_alcance += len(ventas)
    negativas += int((ventas["unit_sales"] < 0).sum())
    ceros += int((ventas["unit_sales"] == 0).sum())
    promociones_nulas += int(ventas["onpromotion"].isna().sum())
    productos_observados.update(ventas["item_nbr"].unique())
    tiendas_observadas.update(ventas["store_nbr"].unique())
    conteos_por_tienda = conteos_por_tienda.add(
        ventas["store_nbr"].value_counts(), fill_value=0
    )
    if ejemplo is None and not ventas.empty:
        ejemplo = ventas.head(5).copy()
    if numero % 10 == 0:
        print(f"Leídas {filas_leidas:,} filas; dentro del alcance: {filas_alcance:,}", flush=True)

print("\nRESULTADOS")
print(f"Filas del archivo completo: {filas_leidas:,}")
print(f"Filas del período, todos los productos: {filas_periodo:,}")
print(f"Filas del período, solo perecederos: {filas_alcance:,}")
print(f"Productos perecederos observados: {len(productos_observados)}")
print(f"Tiendas observadas: {len(tiendas_observadas)}")
print(f"Ventas negativas en el alcance: {negativas:,}")
print(f"Ventas cero explícitas en el alcance: {ceros:,}")
print(f"Promociones nulas en el alcance: {promociones_nulas:,}")
print(f"Filas del período con producto sin catálogo: {productos_sin_catalogo:,}")
print(f"Filas del período con tienda sin catálogo: {tiendas_sin_catalogo:,}")
print("\nEjemplo de registros del alcance:")
if ejemplo is not None:
    print(ejemplo.to_string(index=False))
print("\nCantidad de registros por tienda (no unidades vendidas):")
print(conteos_por_tienda.sort_index().astype("int64").to_string())
print("\nPendiente: validar fechas, duplicados y continuidad de las series.")
