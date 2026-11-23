"""Producción simulada por lotes: lo que corre el flujo de Kestra produccion_lotes.yml.

    python -m src.produccion predecir <lote> <ejecucion>   # el lote de Snowflake → API /predecir/lote
    python -m src.produccion cargar <lote> <ejecucion>     # registro de la API → PRODUCCION.PREDICCIONES
    python -m src.produccion evaluar <paso>                # une con su target los lotes que ya lo tienen

Patrón batch: el pedido de la semana se decide en la reunión del lunes, así que el lote
completo se manda a la API una vez por semana (ver src/lotes.py para el calendario).

predecir. Lee el lote de PRODUCCION.LOTES y lo manda a la API en bloques de TAMANO_BLOQUE
filas. Si la API rechaza un bloque (422), el cliente quita las filas que la respuesta
señala ('filas[i].campo'), las anota como rechazadas y vuelve a mandar el resto: una fila
mal formada no detiene el pedido de toda la semana. Cada bloque lleva como identificador
'lote-<lote>-<ejecucion>', que la API guarda en su registro.

cargar. La API deja cada predicción en su registro de auditoría (RUTA_REGISTRO, un JSONL en
el volumen compartido): id, momento, entradas, pedido, decisión, versión del modelo, run_id
y latencia. Esta tarea carga en PREDICCIONES las líneas de la ejecución indicada (carga
periódica con Kestra, sección 2 del enunciado). Si se repite, primero borra esa ejecución.

evaluar. El paso k de la simulación ocurre el día en que se predice el lote k (para k > 10,
una semana después de la anterior, sin predicción nueva). Ese día ya llegó el target de
los lotes cuya FECHA_LLEGADA_TARGET es anterior o igual: se unen con las predicciones de su
última ejecución y su desempeño queda en PRODUCCION.DESEMPENO. Los lotes ya evaluados no se
repiten. Con 10 lotes, los pasos 11 y 12 solo evalúan los lotes 9 y 10.
"""

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.lotes import COLUMNAS_X, ESQUEMA, calendario_lotes, leer_lote  # noqa: E402

API_URL = os.environ.get('API_URL', 'http://localhost:8000')
RUTA_REGISTRO = os.environ.get('RUTA_REGISTRO', '/registros/predicciones.jsonl')
TAMANO_BLOQUE = 2000
CLAVE = ['STORE_NBR', 'ITEM_NBR', 'DATE']


def etiqueta(lote, ejecucion):
    return f'lote-{int(lote)}-{ejecucion}'


def a_json(datos):
    """Filas listas para la API: nulos como None, fechas como texto y enteros como int."""
    filas = []
    for fila in datos[COLUMNAS_X].astype(object).to_dict('records'):
        limpia = {}
        for columna, valor in fila.items():
            if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
                limpia[columna] = None
            elif hasattr(valor, 'isoformat'):
                limpia[columna] = valor.isoformat()[:10]
            elif isinstance(valor, (np.integer,)):
                limpia[columna] = int(valor)
            elif isinstance(valor, (np.floating,)):
                limpia[columna] = float(valor)
            else:
                limpia[columna] = valor
        filas.append(limpia)
    return filas


def filas_rechazadas(respuesta_422):
    """Índices de las filas que la API señala en un 422 ('filas[3].FAMILY' → 3) y el motivo."""
    rechazadas = {}
    for campo in respuesta_422.get('campos', []):
        indice = re.match(r'filas\[(\d+)\]', campo['campo'])
        if indice:
            rechazadas.setdefault(int(indice.group(1)), []).append(f"{campo['campo'].split('.', 1)[-1]}: {campo['mensaje']}")
    return rechazadas


def mandar_bloque(sesion, filas, identificador):
    """Manda un bloque; si hay filas inválidas, las quita y reintenta una vez con el resto."""
    respuesta = sesion.post(f'{API_URL}/predecir/lote', json={'lote': identificador, 'filas': filas}, timeout=300)
    if respuesta.status_code == 422:
        malas = filas_rechazadas(respuesta.json())
        if not malas:
            respuesta.raise_for_status()
        rechazadas = [{'fila': filas[i], 'motivos': motivos} for i, motivos in malas.items()]
        validas = [fila for i, fila in enumerate(filas) if i not in malas]
        if not validas:
            return None, rechazadas
        respuesta = sesion.post(f'{API_URL}/predecir/lote', json={'lote': identificador, 'filas': validas},
                                timeout=300)
        respuesta.raise_for_status()
        return respuesta.json(), rechazadas
    respuesta.raise_for_status()
    return respuesta.json(), []


def predecir(lote, ejecucion):
    import requests

    datos = leer_lote(lote)
    filas = a_json(datos)
    identificador = etiqueta(lote, ejecucion)
    salud = requests.get(f'{API_URL}/salud', timeout=30).json()
    print(f'API: {salud}')
    aceptadas, rechazadas, versiones, respaldo = 0, [], set(), False
    with requests.Session() as sesion:
        for inicio in range(0, len(filas), TAMANO_BLOQUE):
            respuesta, malas = mandar_bloque(sesion, filas[inicio:inicio + TAMANO_BLOQUE], identificador)
            rechazadas += malas
            if respuesta:
                aceptadas += respuesta['n']
                versiones.add(respuesta['version_modelo'])
                respaldo |= respuesta['respaldo']
    for mala in rechazadas:
        f = mala['fila']
        print(f"  rechazada {f['STORE_NBR']}-{f['ITEM_NBR']}-{f['DATE']}: {'; '.join(mala['motivos'])}")
    resumen = {'lote': int(lote), 'ejecucion': ejecucion, 'filas': len(filas), 'aceptadas': aceptadas,
               'rechazadas': len(rechazadas), 'versiones_modelo': sorted(map(str, versiones)), 'respaldo': respaldo}
    print(json.dumps(resumen, ensure_ascii=False))
    return resumen


def leer_registro(identificador, ruta=RUTA_REGISTRO):
    """Las líneas del registro de la API con ese identificador de lote."""
    filas = []
    with open(ruta, encoding='utf-8') as archivo:
        for linea in archivo:
            if f'"{identificador}"' in linea:
                registro = json.loads(linea)
                if registro.get('lote') == identificador:
                    filas.append(registro)
    return filas


def cargar(lote, ejecucion):
    from snowflake.connector.pandas_tools import write_pandas

    from src.datos import conectar

    registros = leer_registro(etiqueta(lote, ejecucion))
    if not registros:
        raise SystemExit(f'El registro de la API no tiene predicciones de {etiqueta(lote, ejecucion)}.')
    df = pd.DataFrame({
        'ID_PREDICCION': [r['id_prediccion'] for r in registros],
        'FECHA_HORA': [r['momento'] for r in registros],
        'LOTE': int(lote), 'EJECUCION': ejecucion,
        'STORE_NBR': [r['entrada']['STORE_NBR'] for r in registros],
        'ITEM_NBR': [r['entrada']['ITEM_NBR'] for r in registros],
        'DATE': [r['entrada']['DATE'] for r in registros],
        'ENTRADAS': [json.dumps(r['entrada']) for r in registros],
        'PEDIDO': [r['pedido_sugerido'] for r in registros],
        'DECISION': [r['decision'] for r in registros],
        'VERSION_MODELO': [r['version_modelo'] for r in registros],
        'RUN_ID': [r['run_id'] for r in registros],
        'USO_RESPALDO': [bool(r['respaldo']) for r in registros],
        'LATENCIA_MS': [r['latencia_ms'] for r in registros],
        'MODELO': [r.get('modelo') for r in registros],
        'ALIAS': [r.get('alias') for r in registros],
        'MOTIVO_RESPALDO': [r.get('motivo_respaldo') for r in registros],
    })
    columnas = ', '.join(c if c != 'ENTRADAS' else 'PARSE_JSON(ENTRADAS)' for c in df.columns)
    with conectar('PSET4_CARGAR_PREDICCIONES') as con, con.cursor() as cur:
        cur.execute(f'USE SCHEMA {ESQUEMA}')
        write_pandas(con, df, 'PREDICCIONES_CARGA', auto_create_table=True, table_type='temporary',
                     quote_identifiers=False, overwrite=True)
        cur.execute(f'DELETE FROM PREDICCIONES WHERE EJECUCION = %s', (ejecucion,))
        cur.execute(f'INSERT INTO PREDICCIONES ({", ".join(df.columns)}) '
                    f'SELECT {columnas} FROM PREDICCIONES_CARGA')
        insertadas = cur.rowcount
    print(f'PREDICCIONES: {insertadas} filas de {etiqueta(lote, ejecucion)}')
    return insertadas


def fecha_del_paso(paso):
    """Día simulado del paso `paso`: el día en que se predice ese lote, o una semana más por cada paso extra."""
    calendario = calendario_lotes()
    primera = calendario['FECHA_PREDICCION'].min()
    return (primera + pd.Timedelta(days=7 * (int(paso) - 1))).date()


def metricas_desempeno(y, pedido, pedido_regla):
    from sklearn.metrics import mean_pinball_loss

    from src.negocio import CUANTIL, resultado_negocio
    from src.pipeline import rmsle

    modelo, regla = resultado_negocio(y, pedido), resultado_negocio(y, pedido_regla)
    perdida = float(mean_pinball_loss(y, pedido, alpha=CUANTIL))
    return {'FILAS': len(y), 'VENTA_MEDIA': float(np.mean(y)), 'PERDIDA_CUANTIL': perdida,
            'PERDIDA_CUANTIL_RELATIVA': perdida / float(np.mean(y)), 'RMSLE': float(rmsle(y, pedido)),
            'COSTO': modelo['costo'], 'COSTO_REGLA': regla['costo'],
            'AHORRO_VS_REGLA_PCT': 100 * (1 - modelo['costo'] / regla['costo']),
            'MERMA': modelo['merma'], 'COBERTURA': modelo['cobertura'],
            'MERMA_REGLA': regla['merma'], 'COBERTURA_REGLA': regla['cobertura']}


def evaluar(paso):
    from snowflake.connector.pandas_tools import write_pandas

    from src.datos import conectar
    from src.negocio import ReglaRespaldo

    fecha = fecha_del_paso(paso)
    regla = ReglaRespaldo.cargar(RAIZ / 'api' / 'respaldo.json')
    filas = []
    with conectar('PSET4_EVALUAR') as con, con.cursor() as cur:
        cur.execute(f'USE SCHEMA {ESQUEMA}')
        cur.execute("""SELECT DISTINCT t.LOTE FROM LOTES_TARGET t
                       WHERE t.FECHA_LLEGADA_TARGET <= %s
                         AND t.LOTE NOT IN (SELECT LOTE FROM DESEMPENO)
                         AND t.LOTE IN (SELECT LOTE FROM PREDICCIONES)
                       ORDER BY 1""", (fecha,))
        pendientes = [fila[0] for fila in cur.fetchall()]
        for lote in pendientes:
            cur.execute("""SELECT EJECUCION FROM PREDICCIONES WHERE LOTE = %s
                           GROUP BY EJECUCION ORDER BY MAX(FECHA_HORA) DESC LIMIT 1""", (lote,))
            ejecucion = cur.fetchone()[0]
            cur.execute(f"""
                SELECT p.STORE_NBR, p.ITEM_NBR, p.DATE, p.PEDIDO, p.VERSION_MODELO, p.USO_RESPALDO,
                       t.UNIT_SALES_TARGET, l.MEDIA_28_DESDE_16, l.FAMILY
                FROM PREDICCIONES p
                JOIN LOTES_TARGET t USING (STORE_NBR, ITEM_NBR, DATE)
                JOIN LOTES l ON l.STORE_NBR = p.STORE_NBR AND l.ITEM_NBR = p.ITEM_NBR AND l.DATE = p.DATE
                            AND l.DEFECTO IS NULL
                WHERE p.EJECUCION = %s""", (ejecucion,))
            d = cur.fetch_pandas_all()
            pedido_regla = regla.predict(d.rename(columns={'MEDIA_28_DESDE_16': 'media_28_desde_16'}))
            versiones = d['VERSION_MODELO'].dropna().unique()
            filas.append({'LOTE': lote, 'EVALUADO_EN_LOTE': int(paso), 'FECHA_EVALUACION': fecha,
                          'EJECUCION': ejecucion, 'VERSION_MODELO': ','.join(sorted(versiones)) or None,
                          **metricas_desempeno(d['UNIT_SALES_TARGET'].to_numpy(), d['PEDIDO'].to_numpy(),
                                               pedido_regla),
                          'USO_RESPALDO_PCT': 100 * float(d['USO_RESPALDO'].mean())})
        if filas:
            write_pandas(con, pd.DataFrame(filas), 'DESEMPENO', schema=ESQUEMA, quote_identifiers=False)
    for fila in filas:
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else str(v)) for k, v in fila.items()},
                         ensure_ascii=False))
    if not filas:
        print(f'Paso {paso} ({fecha}): ningún lote nuevo con target.')
    return filas


if __name__ == '__main__':
    import warnings
    warnings.filterwarnings('ignore')
    orden = sys.argv[1] if len(sys.argv) > 1 else ''
    if orden == 'predecir':
        predecir(int(sys.argv[2]), sys.argv[3])
    elif orden == 'cargar':
        cargar(int(sys.argv[2]), sys.argv[3])
    elif orden == 'evaluar':
        evaluar(int(sys.argv[2]))
    else:
        print(__doc__)
