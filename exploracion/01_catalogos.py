"""Primer paso: explorar productos y tiendas sin modificar los CSV.

Desde la carpeta Pset2 ejecutar: python exploracion/01_catalogos.py
Requiere pandas. Este diagnóstico inicial no reemplaza la limpieza con dbt.
"""

from pathlib import Path

import pandas as pd


# Localizamos los archivos respecto del script, no de la terminal.
CARPETA_DATOS = Path(__file__).resolve().parents[1]

# Un DataFrame es una tabla en memoria con filas y columnas.
items = pd.read_csv(CARPETA_DATOS / "items.csv")
stores = pd.read_csv(CARPETA_DATOS / "stores.csv")

for nombre, tabla, clave in [
    ("Productos", items, "item_nbr"),
    ("Tiendas", stores, "store_nbr"),
]:
    print(f"\n{nombre}: {tabla.shape[0]} filas y {tabla.shape[1]} columnas")
    print(tabla.head().to_string(index=False))
    print("\nValores ausentes por columna:")
    print(tabla.isna().sum().to_string())
    print(f"Identificadores duplicados: {tabla[clave].duplicated().sum()}")

# La comparación produce True para los productos de nuestro alcance.
# .loc selecciona las filas que cumplen esa condición.
perecederos = items.loc[items["perishable"] == 1].copy()

print(f"\nProductos perecederos del catálogo: {len(perecederos)}")
print("\nProductos perecederos por familia:")
print(perecederos["family"].value_counts().to_string())
print(f"\nCiudades: {stores['city'].nunique()}")
print(f"Provincias: {stores['state'].nunique()}")
