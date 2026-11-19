"""Carga stores.csv a Raw con la misma lógica comprobada para items.

Ejecutar: .venv/Scripts/python.exe snowflake/05_cargar_stores.py
"""

import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    'carga_catalogos', Path(__file__).with_name('04_cargar_items.py')
)
modulo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)


if __name__ == '__main__':
    modulo.cargar_catalogo('stores')
