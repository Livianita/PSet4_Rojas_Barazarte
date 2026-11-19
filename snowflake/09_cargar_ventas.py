"""Carga masiva del alcance mediante PUT y COPY INTO; no limpia ventas.

Ejecutar: .venv/Scripts/python.exe snowflake/09_cargar_ventas.py
La carpeta de extracción puede indicarse con --extract-dir.
"""

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path
from uuid import uuid4


RAIZ = Path(__file__).resolve().parents[1]
COLUMNAS = ['id', 'date', 'store_nbr', 'item_nbr', 'unit_sales', 'onpromotion']


def validar_archivo(carpeta, modo='completo'):
    manifiesto = json.loads((carpeta / 'train_alcance.manifest.json').read_text(encoding='utf-8'))
    archivo = carpeta / 'train_alcance.csv.gz'
    if manifiesto['archivo'] != archivo.name or manifiesto['columnas'] != COLUMNAS:
        raise ValueError('El manifiesto no describe el archivo esperado.')
    inicio, fin = manifiesto['inicio'], manifiesto['fin']
    if any(date.fromisoformat(v).isoformat() != v for v in [inicio, fin]):
        raise ValueError('El manifiesto debe utilizar fechas YYYY-MM-DD.')
    if not '2016-08-01' <= inicio <= fin <= '2017-08-15' or manifiesto['perishable'] != '1':
        raise ValueError('El alcance del manifiesto no coincide con PSET1.')
    if modo == 'completo' and (inicio, fin) != ('2016-08-01', '2017-08-15'):
        raise ValueError('Una extracción parcial solo se admite con --modo intervalo.')
    if not isinstance(manifiesto['filas'], int) or manifiesto['filas'] <= 0:
        raise ValueError('El conteo del manifiesto no es válido.')
    huella = hashlib.sha256()
    with archivo.open('rb') as entrada:
        for bloque in iter(lambda: entrada.read(1024 * 1024), b''):
            huella.update(bloque)
    if archivo.stat().st_size != manifiesto['bytes'] or huella.hexdigest() != manifiesto['sha256']:
        raise ValueError('El archivo cambió respecto del manifiesto; repetir la extracción.')
    with gzip.open(archivo, 'rt', encoding='utf-8', newline='') as entrada:
        if next(csv.reader(entrada), None) != COLUMNAS:
            raise ValueError('El encabezado de la extracción es incorrecto.')
    return archivo, manifiesto


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract-dir', type=Path, default=RAIZ / 'data' / 'extract')
    parser.add_argument('--modo', choices=['completo', 'intervalo'], default='completo')
    args = parser.parse_args()
    archivo, manifiesto = validar_archivo(args.extract_dir, args.modo)
    inicio, fin = manifiesto['inicio'], manifiesto['fin']
    print(f'Archivo y huella verificados: {manifiesto["filas"]:,} filas esperadas.', flush=True)

    spec = importlib.util.spec_from_file_location('conexion_pset2', Path(__file__).with_name('03_probar_conexion.py'))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    lote = str(uuid4())
    with modulo.crear_conexion('PSET2_CARGA_VENTAS') as conexion:
        if conexion.schema.upper() != 'RAW':
            raise ValueError('Configura SNOWFLAKE_SCHEMA=RAW para esta carga.')
        destino = f'{conexion.database}.RAW.TRAIN'
        with conexion.cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS IDENTIFIER(%s) (
                ID VARCHAR, DATE VARCHAR, STORE_NBR VARCHAR, ITEM_NBR VARCHAR,
                UNIT_SALES VARCHAR, ONPROMOTION VARCHAR,
                SOURCE_FILE VARCHAR, SOURCE_ROW_NUMBER NUMBER,
                LOAD_BATCH_ID VARCHAR, LOADED_AT TIMESTAMP_LTZ,
                SOURCE_SHA256 VARCHAR
            )''', (destino,))
            # Los objetos temporales se eliminan al terminar la sesión.
            cursor.execute('''CREATE TEMP STAGE PSET2_TRAIN_STAGE
                FILE_FORMAT = (
                    TYPE = CSV COMPRESSION = GZIP SKIP_HEADER = 1
                    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
                    ESCAPE_UNENCLOSED_FIELD = NONE
                    EMPTY_FIELD_AS_NULL = FALSE NULL_IF = ()
                )''')
            cursor.execute('''CREATE TEMP TABLE TRAIN_CARGA_TEMP (
                ID VARCHAR, DATE VARCHAR, STORE_NBR VARCHAR, ITEM_NBR VARCHAR,
                UNIT_SALES VARCHAR, ONPROMOTION VARCHAR, SOURCE_ROW_NUMBER NUMBER
            )''')
            # Ruta Windows con espacios: usar barras / y literal SQL entre comillas.
            uri = ('file://' + archivo.resolve().as_posix()).replace("'", "''")
            print('Subiendo archivo comprimido al stage temporal...', flush=True)
            cursor.execute(f"PUT '{uri}' @PSET2_TRAIN_STAGE AUTO_COMPRESS=FALSE SOURCE_COMPRESSION=GZIP")
            print('Cargando tabla temporal con COPY INTO...', flush=True)
            cursor.execute('''
                COPY INTO TRAIN_CARGA_TEMP
                FROM (SELECT $1, $2, $3, $4, $5, $6, METADATA$FILE_ROW_NUMBER
                      FROM @PSET2_TRAIN_STAGE)
                ON_ERROR = ABORT_STATEMENT
            ''')
            cursor.execute('SELECT COUNT(*) FROM TRAIN_CARGA_TEMP')
            cantidad = cursor.fetchone()[0]
            if cantidad != manifiesto['filas']:
                raise ValueError(f'COPY cargó {cantidad} filas; se esperaban {manifiesto["filas"]}. Raw no fue reemplazado.')
            cursor.execute('''SELECT COUNT(*) FROM TRAIN_CARGA_TEMP
                WHERE DATE IS NULL OR DATE < %s OR DATE > %s''', (inicio, fin))
            if cursor.fetchone()[0] != 0:
                raise ValueError('La tabla temporal contiene fechas fuera del intervalo; no se modifica Raw.')

            # Solo después de comprobar COPY reemplazamos la fotografía anterior.
            # No ejecutar dos cargas de este mismo archivo simultáneamente.
            cursor.execute('BEGIN')
            try:
                if args.modo == 'intervalo':
                    consulta_exterior = '''SELECT COUNT(*),
                        HASH_AGG(ID, DATE, STORE_NBR, ITEM_NBR, UNIT_SALES, ONPROMOTION, LOAD_BATCH_ID)
                        FROM IDENTIFIER(%s)
                        WHERE DATE < %s OR DATE > %s OR DATE IS NULL'''
                    cursor.execute(consulta_exterior, (destino, inicio, fin))
                    exterior_antes = cursor.fetchone()
                    cursor.execute('DELETE FROM IDENTIFIER(%s) WHERE DATE BETWEEN %s AND %s',
                                   (destino, inicio, fin))
                else:
                    cursor.execute('DELETE FROM IDENTIFIER(%s) WHERE SOURCE_FILE = %s', (destino, archivo.name))
                cursor.execute('''
                    INSERT INTO IDENTIFIER(%s)
                    SELECT ID, DATE, STORE_NBR, ITEM_NBR, UNIT_SALES, ONPROMOTION,
                           %s, SOURCE_ROW_NUMBER, %s, CURRENT_TIMESTAMP(), %s
                    FROM TRAIN_CARGA_TEMP
                ''', (destino, archivo.name, lote, manifiesto['sha256']))
                if args.modo == 'intervalo':
                    cursor.execute('SELECT COUNT(*) FROM IDENTIFIER(%s) WHERE DATE BETWEEN %s AND %s',
                                   (destino, inicio, fin))
                else:
                    cursor.execute('SELECT COUNT(*) FROM IDENTIFIER(%s) WHERE SOURCE_FILE = %s', (destino, archivo.name))
                if cursor.fetchone()[0] != cantidad:
                    raise ValueError('El conteo Raw no coincide; se revierte el reemplazo.')
                if args.modo == 'intervalo':
                    cursor.execute(consulta_exterior, (destino, inicio, fin))
                    if cursor.fetchone() != exterior_antes:
                        raise ValueError('Cambió el conteo o hash fuera del intervalo; se revierte el reemplazo.')
                    print('Fuera del intervalo: conteo y hash de datos/lotes sin cambios.', flush=True)
                cursor.execute('COMMIT')
            except Exception:
                cursor.execute('ROLLBACK')
                raise
    print(f'Carga correcta: {cantidad:,} filas en {destino}.')
    print(f'Lote: {lote}')
    print(f'Modo: {args.modo}; intervalo inclusivo: {inicio} a {fin}')
    print('SOURCE_ROW_NUMBER corresponde al archivo extraído, no a la posición en train.csv.')


if __name__ == '__main__':
    main()
