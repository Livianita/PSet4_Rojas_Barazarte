"""Gold -> uniones en Spark -> candidato verificado -> ANALYTICS.OBT_SALES.

--sample-rows 1000 publica solamente OBT_SALES_SAMPLE, nunca la OBT completa.
No ejecutar en paralelo con recargas o reconstrucciones de Gold.
"""
import argparse
import base64
import importlib.util
import os
from pathlib import Path
import re
import uuid

from cryptography.hazmat.primitives import serialization
from pyspark import StorageLevel
from pyspark.sql import SparkSession, functions as F


# Fuente, alias, clave de unión, columnas: nombre de origen -> nombre OBT.
FUENTES = [
    # Base: panel con ceros reconstruidos. SOURCE_ID (NULL en ceros) se publica como ID.
    ('FCT_SALES_PANEL', 'f', [], {'SOURCE_ID': 'ID', **{n: n for n in (
        'DATE_KEY STORE_KEY ITEM_KEY UNIT_SALES_ORIGINAL UNIT_SALES_TARGET '
        'UNIT_SALES_SOURCE_TEXT IS_RETURN ONPROMOTION IS_ONPROMOTION_IMPUTED '
        'IS_OBSERVED IS_IMPUTED_ZERO IS_AFTER_LAST_SALE SOURCE_FILE SOURCE_ROW_NUMBER '
        'LOAD_BATCH_ID SOURCE_SHA256').split()}}),
    ('DIM_DATE', 'd', ['DATE_KEY'], {n: n for n in (
        'DATE YEAR MONTH DAY_OF_MONTH DAY_OF_WEEK_ISO IS_WEEKEND IS_MONTH_END '
        'IS_PAYDAY_PROXY').split()}),
    ('DIM_ITEM', 'i', ['ITEM_KEY'], {n: n for n in
        'ITEM_NBR FAMILY ITEM_CLASS PERISHABLE'.split()}),
    ('DIM_STORE', 's', ['STORE_KEY'], {n: n for n in
        'STORE_NBR CITY STATE STORE_TYPE STORE_CLUSTER'.split()}),
    ('FCT_STORE_DAY_CONTEXT', 'c', ['DATE_KEY', 'STORE_KEY'], {n: n for n in (
        'APPLICABLE_EVENT_COUNT ACTIVE_HOLIDAY_COUNT IS_HOLIDAY HAS_TRANSFERRED_HOLIDAY '
        'IS_TRANSFER_DAY IS_ADDITIONAL_DAY IS_BRIDGE_DAY IS_WORK_DAY HAS_SPECIAL_EVENT '
        'EVENT_DESCRIPTIONS TRANSACTIONS_OBSERVED HAS_TRANSACTIONS IS_TRANSACTIONS_MISSING '
        'TRANSACTIONS_SOURCE_FILE TRANSACTIONS_SOURCE_ROW_NUMBER TRANSACTIONS_LOAD_BATCH_ID'
    ).split()}),
    ('FCT_OIL_DAILY', 'o', ['DATE_KEY'], {
        'OIL_PRICE_OBSERVED': 'OIL_PRICE_OBSERVED',
        'OIL_PRICE_PREPARED': 'OIL_PRICE_PREPARED',
        'HAS_SOURCE_ROW': 'OIL_HAS_SOURCE_ROW',
        'IS_SOURCE_PRICE_MISSING': 'OIL_IS_SOURCE_PRICE_MISSING',
        'IS_IMPUTED': 'OIL_IS_IMPUTED',
        'PRICE_REFERENCE_DATE': 'OIL_PRICE_REFERENCE_DATE',
        'PRICE_AGE_DAYS': 'OIL_PRICE_AGE_DAYS',
    }),
]
FORMATO = 'net.snowflake.spark.snowflake'
ORDEN_MUESTRA = 'ORDER BY DATE_KEY, STORE_KEY, ITEM_KEY'


def exigir(condicion, mensaje):
    if not condicion:
        raise RuntimeError(mensaje)


def opciones():
    raiz = Path(__file__).resolve().parents[1]
    from dotenv import load_dotenv
    load_dotenv(raiz / '.env', override=False)

    def ruta(nombre):
        p = Path(os.environ[nombre])
        return p if p.is_absolute() else raiz / p

    frase = os.environ.get('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE')
    if not frase:
        frase = ruta('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE').read_text(encoding='utf-8')
    clave = serialization.load_pem_private_key(
        ruta('SNOWFLAKE_PRIVATE_KEY_FILE').read_bytes(), password=frase.encode('utf-8'))
    privada = base64.b64encode(clave.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())).decode('ascii')
    cuenta = os.environ['SNOWFLAKE_ACCOUNT'].strip()
    db = os.environ['SNOWFLAKE_DATABASE'].strip()
    exigir(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', db), 'Nombre de base de datos inválido.')
    return dict(sfURL=f'{cuenta}.snowflakecomputing.com',
                sfUser=os.environ['SNOWFLAKE_USER'],
                sfRole=os.environ['SNOWFLAKE_ROLE'],
                sfWarehouse=os.environ['SNOWFLAKE_WAREHOUSE'],
                sfDatabase=db, sfSchema='GOLD', pem_private_key=privada,
                autopushdown='off', continue_on_error='off', usestagingtable='on'), db


def conexion_control():
    archivo = Path(__file__).resolve().parents[1] / 'snowflake' / '03_probar_conexion.py'
    spec = importlib.util.spec_from_file_location('conexion_pset2', archivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.crear_conexion('PSET2_SPARK_OBT_VALIDACION')


def consulta_esperada(db, muestra):
    ventas = f'{db}.GOLD.FCT_SALES_PANEL'
    if muestra:
        ventas = f'(SELECT * FROM {ventas} {ORDEN_MUESTRA} LIMIT {muestra})'
    columnas = ', '.join(f'{alias}."{origen}" AS "{destino}"'
                          for _, alias, _, campos in FUENTES
                          for origen, destino in campos.items())
    sql = f'SELECT {columnas} FROM {ventas} f'
    for tabla, alias, claves, _ in FUENTES[1:]:
        predicado = ' AND '.join(f'f.{k} = {alias}.{k}' for k in claves)
        sql += f' LEFT JOIN {db}.GOLD.{tabla} {alias} ON {predicado}'
    return sql


def resumir(df, id_col='ID', observado='IS_OBSERVED'):
    # countDistinct ignora NULL: cuenta solo IDs de ventas observadas.
    return df.agg(F.count('*').alias('filas'), F.countDistinct(id_col).alias('ids'),
                  F.sum(F.col(observado).cast('int')).alias('observadas'),
                  F.sum('UNIT_SALES_ORIGINAL').alias('original'),
                  F.sum('UNIT_SALES_TARGET').alias('objetivo')).first()


def construir(spark, opts, db, muestra):
    marcos = []
    for tabla, alias, claves, campos in FUENTES:
        columnas = ', '.join(f'"{n}"' for n in dict.fromkeys(claves + list(campos)))
        consulta = f'SELECT {columnas} FROM {db}.GOLD.{tabla}'
        if alias == 'f' and muestra:
            consulta += f' {ORDEN_MUESTRA} LIMIT {muestra}'
        df = spark.read.format(FORMATO).options(**opts).option('query', consulta).load()
        if claves:
            df = df.persist(StorageLevel.MEMORY_AND_DISK)
            exigir(df.filter(F.expr(' OR '.join(f'{k} IS NULL' for k in claves))).limit(1).count() == 0,
                   f'{tabla}: clave nula.')
            exigir(df.groupBy(*claves).count().filter('count > 1').limit(1).count() == 0,
                   f'{tabla}: claves duplicadas; se cancela la unión.')
        else:
            df = df.persist(StorageLevel.DISK_ONLY)
        marcos.append(df.alias(alias))
        print('Fuente leída y claves comprobadas:', tabla, flush=True)
    base = resumir(marcos[0], id_col='SOURCE_ID')
    exigir(base.filas > 0 and base.ids == base.observadas,
           'Panel vacío, IDs duplicados o venta observada sin ID.')
    resultado = marcos[0]
    for (_, alias, claves, _), df in zip(FUENTES[1:], marcos[1:]):
        condicion = F.lit(True)
        for clave in claves:
            condicion = condicion & (F.col(f'f.{clave}') == F.col(f'{alias}.{clave}'))
        resultado = resultado.join(F.broadcast(df), condicion, 'left')
    resultado = resultado.select(*[
        F.col(f'{alias}.{origen}').alias(destino)
        for _, alias, _, campos in FUENTES for origen, destino in campos.items()
    ]).persist(StorageLevel.DISK_ONLY)
    final = resumir(resultado)
    exigir(tuple(base) == tuple(final), 'La OBT cambia filas, IDs, observaciones o sumas de ventas.')
    exigir(resultado.select('DATE_KEY', 'STORE_KEY', 'ITEM_KEY').distinct().count() == final.filas,
           'La OBT tiene claves fecha-tienda-producto duplicadas.')
    requeridos = ['DATE', 'ITEM_NBR', 'STORE_NBR', 'HAS_TRANSACTIONS',
                  'OIL_IS_IMPUTED', 'OIL_PRICE_PREPARED']
    exigir(resultado.filter(F.expr(' OR '.join(f'{n} IS NULL' for n in requeridos))).limit(1).count() == 0,
           'La OBT tiene filas sin dimensión o sin contexto preparado.')
    exigir(resultado.filter('UNIT_SALES_TARGET < 0 OR PERISHABLE <> 1').limit(1).count() == 0,
           'Objetivo negativo o producto fuera del alcance.')
    exigir(resultado.filter('IS_IMPUTED_ZERO AND (UNIT_SALES_TARGET <> 0 OR ID IS NOT NULL)')
           .limit(1).count() == 0, 'Cero reconstruido con venta o ID.')
    print(f'Uniones en Spark correctas: {final.filas:,} filas, {final.observadas:,} observadas '
          f'y {final.filas - final.observadas:,} ceros reconstruidos.', flush=True)
    for df in marcos:
        df.unpersist()
    return resultado, final.filas


def publicar(resultado, opts, db, muestra, filas):
    nombre = 'OBT_SALES_SAMPLE' if muestra else 'OBT_SALES'
    candidato = f'{nombre}_BUILD_{uuid.uuid4().hex.upper()}'
    completo = f'{db}.ANALYTICS.{candidato}'
    esperado = consulta_esperada(db, muestra)
    columnas = ', '.join(f'"{n}"' for n in resultado.columns)
    with conexion_control() as conexion, conexion.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA IF NOT EXISTS {db}.ANALYTICS')
        try:
            resultado.write.format(FORMATO).options(**dict(opts, sfSchema='ANALYTICS')).option(
                'dbtable', candidato).mode('errorifexists').save()
            cursor.execute(f'SELECT COUNT(*) FROM {completo}')
            exigir(cursor.fetchone()[0] == filas, 'La escritura perdió filas.')
            # Compara cada columna, incluidos nulos, en ambas direcciones.
            cursor.execute(f'''WITH esperado AS ({esperado}),
                faltantes AS (SELECT {columnas} FROM esperado MINUS SELECT {columnas} FROM {completo}),
                sobrantes AS (SELECT {columnas} FROM {completo} MINUS SELECT {columnas} FROM esperado)
                SELECT (SELECT COUNT(*) FROM faltantes), (SELECT COUNT(*) FROM sobrantes)''')
            exigir(tuple(cursor.fetchone()) == (0, 0), 'La tabla escrita difiere de Gold; no se publica.')
            cursor.execute(f'''SELECT COUNT(*) FROM {db}.INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = 'ANALYTICS' AND TABLE_NAME = %s''', (nombre,))
            if cursor.fetchone()[0]:
                cursor.execute(f'ALTER TABLE {completo} SWAP WITH {db}.ANALYTICS.{nombre}')
                cursor.execute(f'DROP TABLE {completo}')
            else:
                cursor.execute(f'ALTER TABLE {completo} RENAME TO {db}.ANALYTICS.{nombre}')
            print(f'OBT publicada y verificada: {filas:,} filas en {db}.ANALYTICS.{nombre}.', flush=True)
        except BaseException:
            cursor.execute(f'DROP TABLE IF EXISTS {completo}')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-rows', type=int, default=0)
    args = parser.parse_args()
    exigir(0 <= args.sample_rows <= 10000, 'Muestra permitida: 1 a 10000; 0 significa carga completa.')
    opts, db = opciones()
    spark = SparkSession.builder.appName('PSET2_OBT_SALES').getOrCreate()
    spark.sparkContext.setLogLevel('WARN')
    try:
        resultado, filas = construir(spark, opts, db, args.sample_rows)
        publicar(resultado, opts, db, args.sample_rows, filas)
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
