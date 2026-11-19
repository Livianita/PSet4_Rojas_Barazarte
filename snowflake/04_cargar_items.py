"""Primera carga Raw, repetible secuencialmente, del catálogo completo.

Ejecutar: .venv/Scripts/python.exe snowflake/04_cargar_items.py
La frase se solicita en terminal salvo que esté configurada en el entorno.
"""

import csv
import importlib.util
import os
from pathlib import Path
from uuid import uuid4


# Reutilizamos la conexión ya probada. El nombre comienza por un número,
# por lo que lo cargamos con importlib en lugar de un import convencional.
RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('conexion_pset2', Path(__file__).with_name('03_probar_conexion.py'))
modulo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)


CATALOGOS = {
    'items': ['item_nbr', 'family', 'class', 'perishable'],
    'stores': ['store_nbr', 'city', 'state', 'type', 'cluster'],
    'oil': ['date', 'dcoilwtico'],
    'transactions': ['date', 'store_nbr', 'transactions'],
    'holidays_events': ['date', 'type', 'locale', 'locale_name', 'description', 'transferred'],
}


def leer_catalogo(ruta, columnas):
    with ruta.open(encoding='utf-8-sig', newline='') as archivo:
        lector = csv.reader(archivo)
        if next(lector, None) != columnas:
            raise ValueError(f'El encabezado de {ruta.name} no coincide con el esperado.')
        filas = list(lector)
    if not filas or any(len(fila) != len(columnas) for fila in filas):
        raise ValueError('El catálogo está vacío o contiene filas con estructura incorrecta.')
    return filas


def leer_items(ruta):
    return leer_catalogo(ruta, CATALOGOS['items'])


def cargar_catalogo(nombre):
    # Solo nombres y columnas de esta lista fija se incorporan al SQL.
    columnas = CATALOGOS[nombre]
    archivo_origen = nombre + '.csv'
    columnas_sql = ', '.join(columna.upper() for columna in columnas)
    definiciones_sql = ', '.join(columna.upper() + ' VARCHAR' for columna in columnas)
    marcadores = ', '.join(['%s'] * (len(columnas) + 1))
    # DATA_DIR permite al profesor indicar su propia ubicación de los CSV.
    # Primero abrir conexión carga .env; no se ejecuta ninguna escritura aún.
    with modulo.crear_conexion('PSET2_CARGA_' + nombre.upper()) as conexion:
        carpeta = Path(os.environ.get('DATA_DIR', str(RAIZ)))
        if not carpeta.is_absolute():
            carpeta = RAIZ / carpeta
        filas = leer_catalogo(carpeta / archivo_origen, columnas)
        if conexion.schema.upper() != 'RAW':
            raise ValueError('Para esta carga, configura SNOWFLAKE_SCHEMA=RAW.')
        destino = f'{conexion.database}.RAW.{nombre.upper()}'
        lote = str(uuid4())
        with conexion.cursor() as cursor:
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS IDENTIFIER(%s) (
                    {definiciones_sql},
                    SOURCE_FILE VARCHAR, SOURCE_ROW_NUMBER NUMBER,
                    LOAD_BATCH_ID VARCHAR, LOADED_AT TIMESTAMP_LTZ
                )
            ''', (destino,))
            # Primero preparar y comprobar en una tabla temporal de la sesión.
            cursor.execute(f'''CREATE TEMP TABLE CATALOGO_CARGA_TEMP (
                {definiciones_sql},
                SOURCE_ROW_NUMBER NUMBER
            )''')
            # Lotes pequeños limitan el tamaño de cada envío al servidor.
            for inicio in range(0, len(filas), 1000):
                cursor.executemany(
                    f'INSERT INTO CATALOGO_CARGA_TEMP VALUES ({marcadores})',
                    [tuple(fila) + (numero,) for numero, fila in enumerate(
                        filas[inicio:inicio + 1000], start=inicio + 1
                    )],
                )
            cursor.execute('SELECT COUNT(*) FROM CATALOGO_CARGA_TEMP')
            if cursor.fetchone()[0] != len(filas):
                raise ValueError('La carga temporal no coincide con el CSV.')

            # El reemplazo de la fotografía del catálogo es atómico: si falla,
            # ROLLBACK conserva el lote anterior. No ejecutar cargas concurrentes.
            cursor.execute('BEGIN')
            try:
                cursor.execute('DELETE FROM IDENTIFIER(%s) WHERE SOURCE_FILE = %s',
                               (destino, archivo_origen))
                cursor.execute(f'''
                    INSERT INTO IDENTIFIER(%s)
                    SELECT {columnas_sql},
                           %s, SOURCE_ROW_NUMBER, %s, CURRENT_TIMESTAMP()
                    FROM CATALOGO_CARGA_TEMP
                ''', (destino, archivo_origen, lote))
                cursor.execute('SELECT COUNT(*) FROM IDENTIFIER(%s) WHERE SOURCE_FILE = %s',
                               (destino, archivo_origen))
                cantidad = cursor.fetchone()[0]
                if cantidad != len(filas):
                    raise ValueError('La cantidad Raw no coincide con el CSV; se revierte la carga.')
                cursor.execute('COMMIT')
            except Exception:
                cursor.execute('ROLLBACK')
                raise
        print(f'Carga correcta: {cantidad:,} filas en {destino}.')
        print(f'Lote: {lote}')
        print('Valores originales conservados como texto; no se aplicó limpieza.')


def main():
    cargar_catalogo('items')


if __name__ == '__main__':
    main()
