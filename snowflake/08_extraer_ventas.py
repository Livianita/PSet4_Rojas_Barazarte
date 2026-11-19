"""Extrae el alcance de ventas, sin limpiar valores ni conectar con Snowflake.

Ejecutar: .venv/Scripts/python.exe snowflake/08_extraer_ventas.py
Requiere duckdb. DATA_DIR se admite como variable del entorno o --data-dir.
"""

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import duckdb


RAIZ = Path(__file__).resolve().parents[1]
FECHA_INICIO = '2016-08-01'
FECHA_FIN = '2017-08-15'


def validar_intervalo(inicio, fin):
    for valor in [inicio, fin]:
        if date.fromisoformat(valor).isoformat() != valor:
            raise ValueError('Usar fechas con formato YYYY-MM-DD.')
    if not FECHA_INICIO <= inicio <= fin <= FECHA_FIN:
        raise ValueError(f'El intervalo debe estar entre {FECHA_INICIO} y {FECHA_FIN}, en orden.')


def extraer(carpeta, salida, inicio=FECHA_INICIO, fin=FECHA_FIN):
    validar_intervalo(inicio, fin)
    salida.mkdir(parents=True, exist_ok=True)
    temporal = salida / 'train_alcance.tmp.csv.gz'
    destino = salida / 'train_alcance.csv.gz'
    with duckdb.connect() as conexion:
        conexion.execute("SET memory_limit = '512MB'")
        conexion.execute('SET threads = 2')
        conexion.execute('SET temp_directory = ?', [str(salida / '.duckdb_tmp')])
        conexion.read_csv(str(carpeta / 'train.csv'), all_varchar=True).create_view('ventas')
        conexion.read_csv(str(carpeta / 'items.csv'), all_varchar=True).create_view('items')
        # SEMIJOIN mediante IN: cada venta se selecciona una vez incluso si
        # el catálogo tuviera claves repetidas. No se convierten las cantidades.
        consulta = conexion.sql('''
            SELECT id, date, store_nbr, item_nbr, unit_sales, onpromotion
            FROM ventas
            WHERE date BETWEEN ? AND ?
              AND item_nbr IN (SELECT item_nbr FROM items WHERE perishable = '1')
        ''', params=[inicio, fin])
        print('Extrayendo perecederos del período a CSV comprimido...', flush=True)
        consulta.write_csv(str(temporal), header=True, compression='gzip')
        conexion.read_csv(str(temporal), all_varchar=True).create_view('extraido')
        filas, minima, maxima = conexion.execute('''
            SELECT count(*), min(date), max(date) FROM extraido
        ''').fetchone()
        if filas == 0 or minima < inicio or maxima > fin:
            raise ValueError('La extracción está vacía o tiene fechas fuera del alcance.')

    # Huella del archivo generado para identificar exactamente qué se cargará.
    huella = hashlib.sha256()
    with temporal.open('rb') as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b''):
            huella.update(bloque)
    manifiesto = {
        'archivo': destino.name,
        'fuentes': ['train.csv', 'items.csv'],
        'inicio': inicio, 'fin': fin, 'perishable': '1',
        'filas': filas, 'primera_fecha': minima, 'ultima_fecha': maxima,
        'bytes': temporal.stat().st_size, 'sha256': huella.hexdigest(),
        'columnas': ['id', 'date', 'store_nbr', 'item_nbr', 'unit_sales', 'onpromotion'],
        'nota': 'Extracción acotada; no representa todo train.csv. Sin limpieza ni imputación.',
    }
    # Reemplazar solo después de comprobar el archivo temporal.
    temporal.replace(destino)
    manifiesto_path = salida / 'train_alcance.manifest.json'
    manifiesto_path.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Extracción correcta: {filas:,} filas.')
    print(f'Fechas: {minima} a {maxima}')
    print(f'Archivo: {destino}')
    print(f'Tamaño comprimido: {manifiesto["bytes"] / 1024**2:.2f} MiB')
    print(f'Manifiesto: {manifiesto_path}')
    return manifiesto


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DATA_DIR', str(RAIZ))))
    parser.add_argument('--salida', type=Path, default=RAIZ / 'data' / 'extract')
    parser.add_argument('--inicio', default=FECHA_INICIO)
    parser.add_argument('--fin', default=FECHA_FIN)
    args = parser.parse_args()
    carpeta = args.data_dir if args.data_dir.is_absolute() else RAIZ / args.data_dir
    extraer(carpeta, args.salida, args.inicio, args.fin)


if __name__ == '__main__':
    main()
