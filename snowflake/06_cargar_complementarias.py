"""Carga una fuente complementaria completa a Raw sin limpiarla.

Ejemplo: .venv/Scripts/python.exe snowflake/06_cargar_complementarias.py oil
Opciones: oil, transactions, holidays_events.
El lector compartido carga el archivo pequeño en memoria; no usar para train.
"""

import argparse
import importlib.util
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Carga una fuente complementaria a Snowflake Raw.')
    parser.add_argument('fuente', choices=['oil', 'transactions', 'holidays_events'])
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        'carga_fuentes', Path(__file__).with_name('04_cargar_items.py')
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    modulo.cargar_catalogo(args.fuente)


if __name__ == '__main__':
    main()
