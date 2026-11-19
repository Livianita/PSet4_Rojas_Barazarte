"""Acceso a la OBT del PSet 2 en Snowflake y snapshot local reproducible.

Uso desde un notebook (carpeta notebooks/):

    import sys; sys.path.insert(0, '..')
    from src.datos import cargar_muestra, consultar
    ventas, meta = cargar_muestra()        # extrae de Snowflake la primera vez

Uso desde una terminal, en la raíz del repositorio:

    python -m src.datos            # crea (o verifica) data/obt_muestra.parquet

Decisiones:
- La experimentación usa una muestra de series tienda-producto, no la OBT
  completa (13 M filas): 3 modelos x 30 configuraciones x 5 pliegues no caben
  en un equipo de 12 GB. La muestra es estratificada y proporcional por familia,
  con semilla fija, y conserva cada serie completa en el tiempo.
- Elegibilidad: series cuya primera fila del panel es anterior a
  FECHA_LIMITE_HISTORIA. No se filtra por actividad en la ventana de prueba:
  eso usaría información futura para elegir la muestra.
- La huella (SHA-256) se calcula sobre el contenido, ordenado por clave, y se
  registra en MLflow junto con la tabla de origen y la fecha de corte.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import snowflake.connector
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
DIR_DATOS = RAIZ / 'data'
RUTA_MUESTRA = DIR_DATOS / 'obt_muestra.parquet'
RUTA_META = DIR_DATOS / 'obt_muestra_meta.json'

N_SERIES = 2000
SEMILLA = 42
FECHA_LIMITE_HISTORIA = '2017-06-15'
CLAVE = ['STORE_NBR', 'ITEM_NBR', 'DATE']

# Columnas que se extraen. Las de procedencia (archivo, fila, lote, SHA del
# extracto) quedan en Snowflake. Las marcas de auditoría se traen solo para el
# EDA y la evaluación: nunca son variables del modelo (ver src/pipeline.py).
COLUMNAS = {
    'DATE': 'DATE',
    'STORE_NBR': 'STORE_NBR::INT',
    'ITEM_NBR': 'ITEM_NBR::INT',
    'UNIT_SALES_TARGET': 'UNIT_SALES_TARGET::FLOAT',
    'UNIT_SALES_ORIGINAL': 'UNIT_SALES_ORIGINAL::FLOAT',
    'IS_RETURN': 'IS_RETURN',
    'ONPROMOTION': 'ONPROMOTION',
    'IS_OBSERVED': 'IS_OBSERVED',
    'IS_IMPUTED_ZERO': 'IS_IMPUTED_ZERO',
    'IS_ONPROMOTION_IMPUTED': 'IS_ONPROMOTION_IMPUTED',
    'IS_AFTER_LAST_SALE': 'IS_AFTER_LAST_SALE',
    'YEAR': 'YEAR::INT',
    'MONTH': 'MONTH::INT',
    'DAY_OF_MONTH': 'DAY_OF_MONTH::INT',
    'DAY_OF_WEEK_ISO': 'DAY_OF_WEEK_ISO::INT',
    'IS_WEEKEND': 'IS_WEEKEND',
    'IS_MONTH_END': 'IS_MONTH_END',
    'IS_PAYDAY_PROXY': 'IS_PAYDAY_PROXY',
    'FAMILY': 'FAMILY',
    'ITEM_CLASS': 'ITEM_CLASS::INT',
    'CITY': 'CITY',
    'STATE': 'STATE',
    'STORE_TYPE': 'STORE_TYPE',
    'STORE_CLUSTER': 'STORE_CLUSTER::INT',
    'APPLICABLE_EVENT_COUNT': 'APPLICABLE_EVENT_COUNT::INT',
    'ACTIVE_HOLIDAY_COUNT': 'ACTIVE_HOLIDAY_COUNT::INT',
    'IS_HOLIDAY': 'IS_HOLIDAY',
    'IS_TRANSFER_DAY': 'IS_TRANSFER_DAY',
    'IS_ADDITIONAL_DAY': 'IS_ADDITIONAL_DAY',
    'IS_BRIDGE_DAY': 'IS_BRIDGE_DAY',
    'IS_WORK_DAY': 'IS_WORK_DAY',
    'HAS_SPECIAL_EVENT': 'HAS_SPECIAL_EVENT',
    'TRANSACTIONS_OBSERVED': 'TRANSACTIONS_OBSERVED::FLOAT',
    'IS_TRANSACTIONS_MISSING': 'IS_TRANSACTIONS_MISSING',
    'OIL_PRICE_PREPARED': 'OIL_PRICE_PREPARED::FLOAT',
}


# --------------------------------------------------------------------------- #
# Conexión
# --------------------------------------------------------------------------- #
def _ruta(valor: str) -> Path:
    p = Path(valor)
    return p if p.is_absolute() else (RAIZ / p).resolve()


def tabla_obt() -> str:
    load_dotenv(RAIZ / '.env', override=False)
    tabla = os.environ.get('SNOWFLAKE_OBT_TABLE', 'ANALYTICS.OBT_SALES').strip()
    if not re.fullmatch(r'[A-Za-z_][\w]*(\.[A-Za-z_][\w]*){0,2}', tabla):
        raise ValueError('SNOWFLAKE_OBT_TABLE no es un nombre de tabla válido.')
    return tabla


def conectar(query_tag: str = 'PSET3') -> snowflake.connector.SnowflakeConnection:
    """Conexión por clave RSA (la misma del PSet 2). Lee .env de la raíz."""
    load_dotenv(RAIZ / '.env', override=False)
    req = {k: os.environ.get(f'SNOWFLAKE_{k}', '').strip()
           for k in ('ACCOUNT', 'USER', 'ROLE', 'WAREHOUSE', 'DATABASE', 'PRIVATE_KEY_FILE')}
    faltan = [k for k, v in req.items() if not v or v.startswith('tu_')]
    if faltan:
        raise SystemExit(f'Completa en .env: {", ".join("SNOWFLAKE_" + k for k in faltan)}')

    frase = os.environ.get('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE') or None
    if not frase:
        archivo = os.environ.get('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE', '').strip()
        if archivo and _ruta(archivo).is_file():
            frase = _ruta(archivo).read_text(encoding='utf-8')
    clave = serialization.load_pem_private_key(
        _ruta(req['PRIVATE_KEY_FILE']).read_bytes(),
        password=frase.encode('utf-8') if frase else None)
    privada = clave.private_bytes(serialization.Encoding.DER,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    return snowflake.connector.connect(
        account=req['ACCOUNT'], user=req['USER'], role=req['ROLE'],
        warehouse=req['WAREHOUSE'], database=req['DATABASE'],
        authenticator='SNOWFLAKE_JWT', private_key=privada,
        session_parameters={'QUERY_TAG': query_tag}, login_timeout=30)


def consultar(sql: str, query_tag: str = 'PSET3_CONSULTA') -> pd.DataFrame:
    """Ejecuta una consulta de solo lectura y devuelve un DataFrame."""
    with conectar(query_tag) as con, con.cursor() as cur:
        cur.execute(sql)
        return cur.fetch_pandas_all()


# --------------------------------------------------------------------------- #
# Muestra de series
# --------------------------------------------------------------------------- #
def seleccionar_series(series: pd.DataFrame, n: int = N_SERIES,
                       semilla: int = SEMILLA) -> pd.DataFrame:
    """Muestra estratificada proporcional por familia (asignación por restos mayores).

    `series` tiene STORE_NBR, ITEM_NBR, FAMILY. El orden de entrada no influye:
    se ordena por clave antes de muestrear.
    """
    series = series.sort_values(['FAMILY', 'STORE_NBR', 'ITEM_NBR']).reset_index(drop=True)
    tam = series['FAMILY'].value_counts().sort_index()
    cuota = tam / tam.sum() * n
    asignado = cuota.astype(int)
    resto = n - asignado.sum()
    asignado[(cuota - asignado).sort_values(ascending=False).index[:resto]] += 1
    partes = [g.sample(n=int(asignado[f]), random_state=semilla)
              for f, g in series.groupby('FAMILY', sort=True)]
    return pd.concat(partes).sort_values(['STORE_NBR', 'ITEM_NBR']).reset_index(drop=True)


def huella(df: pd.DataFrame) -> str:
    """SHA-256 del contenido, independiente del orden de filas y columnas y de
    la representación en memoria (parquet guarda fechas en ms y textos como
    'str'; en memoria pueden ser ns y 'object')."""
    d = df.sort_values(CLAVE).reset_index(drop=True)
    d = d[sorted(d.columns)].copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime('%Y-%m-%d')
        elif pd.api.types.is_string_dtype(d[c]) or d[c].dtype == object:
            d[c] = d[c].astype(object)
    h = hashlib.sha256()
    h.update(','.join(d.columns).encode())
    h.update(pd.util.hash_pandas_object(d, index=False).values.tobytes())
    return h.hexdigest()


def extraer_muestra(n: int = N_SERIES, semilla: int = SEMILLA) -> tuple[pd.DataFrame, dict]:
    """Extrae de Snowflake la muestra de series y la guarda como snapshot local."""
    tabla = tabla_obt()
    with conectar('PSET3_EXTRAER_MUESTRA') as con, con.cursor() as cur:
        cur.execute(f"""
            SELECT STORE_NBR::INT AS STORE_NBR, ITEM_NBR::INT AS ITEM_NBR, ANY_VALUE(FAMILY) AS FAMILY
            FROM {tabla}
            GROUP BY 1, 2
            HAVING MIN(DATE) <= DATE '{FECHA_LIMITE_HISTORIA}'""")
        elegibles = cur.fetch_pandas_all()
        elegidas = seleccionar_series(elegibles, n, semilla)

        valores = ', '.join(f'({s}, {i})' for s, i in
                            elegidas[['STORE_NBR', 'ITEM_NBR']].itertuples(index=False))
        columnas = ', '.join(f'o.{expr} AS {alias}' for alias, expr in COLUMNAS.items())
        cur.execute(f"""
            WITH m(STORE_NBR, ITEM_NBR) AS (SELECT * FROM VALUES {valores})
            SELECT {columnas}
            FROM {tabla} o
            JOIN m ON o.STORE_NBR = m.STORE_NBR AND o.ITEM_NBR = m.ITEM_NBR
            ORDER BY STORE_NBR, ITEM_NBR, DATE""")
        ventas = cur.fetch_pandas_all()

        cur.execute(f'SELECT COUNT(*), MIN(DATE), MAX(DATE) FROM {tabla}')
        filas_obt, fecha_min, fecha_max = cur.fetchone()
        esquema, nombre = tabla.split('.')[-2:]
        cur.execute(f"""SELECT LAST_ALTERED FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_SCHEMA = '{esquema}' AND TABLE_NAME = '{nombre}'""")
        ultima_modificacion = cur.fetchone()[0]

    ventas['DATE'] = pd.to_datetime(ventas['DATE'])
    # La huella se calcula sobre lo que se lee del disco: es lo que usan los notebooks.
    DIR_DATOS.mkdir(exist_ok=True)
    ventas.to_parquet(RUTA_MUESTRA, index=False)
    ventas = pd.read_parquet(RUTA_MUESTRA)
    meta = {
        'tabla_origen': f'{os.environ["SNOWFLAKE_DATABASE"]}.{tabla}',
        'filas_obt': int(filas_obt),
        'fecha_min': str(fecha_min),
        'fecha_corte_snapshot': str(fecha_max),
        'obt_last_altered': str(ultima_modificacion),
        'extraido_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'series_elegibles': int(len(elegibles)),
        'n_series': int(n),
        'semilla_muestra': int(semilla),
        'fecha_limite_historia': FECHA_LIMITE_HISTORIA,
        'filas_muestra': int(len(ventas)),
        'series_por_familia': elegidas['FAMILY'].value_counts().sort_index().to_dict(),
        'sha256': huella(ventas),
    }
    RUTA_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    return ventas, meta


def cargar_muestra(extraer_si_falta: bool = True) -> tuple[pd.DataFrame, dict]:
    """Lee el snapshot local y verifica que su huella coincida con la registrada."""
    if not RUTA_MUESTRA.exists():
        if not extraer_si_falta:
            raise FileNotFoundError(RUTA_MUESTRA)
        return extraer_muestra()
    ventas = pd.read_parquet(RUTA_MUESTRA)
    meta = json.loads(RUTA_META.read_text(encoding='utf-8'))
    if huella(ventas) != meta['sha256']:
        raise RuntimeError('El snapshot local no coincide con su huella: vuelve a extraerlo.')
    return ventas, meta


if __name__ == '__main__':
    ventas, meta = cargar_muestra()
    print(json.dumps({k: v for k, v in meta.items() if k != 'series_por_familia'},
                     indent=2, ensure_ascii=False))
    print('Series por familia:', meta['series_por_familia'])
