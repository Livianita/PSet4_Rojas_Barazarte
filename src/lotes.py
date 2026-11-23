"""Lotes semanales de la simulación de producción (PSet 4, sección 5).

    python -m src.lotes tablas      # crea el esquema PRODUCCION y sus tablas (snowflake/30_tablas_produccion.sql)
    python -m src.lotes construir   # arma los lotes y los sube a PRODUCCION.LOTES y LOTES_TARGET
    python -m src.lotes resumen     # filas y fechas de cada lote, leídas de Snowflake

Calendario. Un lote es una semana de ventas (lunes a domingo) de las 2.000 series de la
muestra. La reunión de pedidos es el lunes anterior a la semana: ese día se conocen las
ventas hasta el domingo previo, y el día más tardío del lote (domingo, t) solo necesita
datos hasta t−16, que ya existen. El target de la semana se conoce el lunes siguiente a
su cierre, que es el día en que se predice el lote k+2: el target llega dos lotes después
de la predicción, nunca junto con ella.

El primer lote empieza el lunes 2017-06-05. Se predice el 2017-05-29 con datos hasta el
2017-05-28, que es el corte de entrenamiento del champion (src/reentrenar.py): ningún lote
usa información que el modelo no habría tenido. Hasta el 2017-08-13 caben 10 lotes
completos; el 14 y el 15 de agosto quedan fuera por no formar una semana.

Las features se calculan con construir_features de src/pipeline.py sobre el snapshot de la
OBT (data/obt_muestra.parquet). Como cada feature mira 16 días o más hacia atrás, calcularlas
sobre la serie completa da lo mismo que calcularlas el día de la predicción.

Alteraciones intencionales (columna DERIVA de cada lote). Los lotes 1, 2 y 4 no se tocan:
son el control de falsas alarmas.

1. Lote 3, DERIVA = 'fuente_transacciones': deriva de datos sin impacto. La feature
   transacciones_lag_16 llega en otra escala: log1p(transacciones × 0,5), como si el
   sistema de cajas empezara a contar la mitad de las transacciones. Solo se altera esa
   feature, solo en ese lote, y la venta real no cambia. Su PSI pasa de ≈ 0,03 a ≈ 2,5,
   pero la pérdida del modelo casi no se mueve (1,597 contra 1,595 en una prueba sobre el
   lote 2): la feature pesa poco en el modelo. Diagnóstico esperado: revisar la fuente,
   no reentrenar.
   El mismo lote trae además FILAS_DEFECTUOSAS: tres copias de filas reales con un defecto
   cada una (un campo obligatorio vacío, un valor fuera de rango y una familia que no existe
   en el entrenamiento). El servicio debe rechazarlas con 422; el monitoreo las cuenta en
   los faltantes, los valores fuera de rango y las categorías no vistas. No tienen target.

2. Lotes 5 a 10, DERIVA = 'demanda': aumento sostenido de la demanda. Desde el lunes del
   lote 5 (2017-07-03), la venta real (UNIT_SALES_TARGET) de todas las series se multiplica
   por 1,5 y se queda así, como lo dejaría el cierre de un competidor. Solo se altera la
   venta; las features se recalculan a partir de la venta alterada, como ocurriría en
   producción. Por eso la deriva aparece en dos tiempos:
   - lotes 5 a 7: las entradas todavía miran ventas anteriores al cambio (t−16) y se ven
     normales, pero la venta real sube: deriva conceptual, visible solo cuando llega el target;
   - lotes 8 a 10: los rezagos ya recogen el aumento y cambia la distribución de las entradas
     (venta_lag_16, media_7_desde_16): deriva de datos con impacto, visible el día de la predicción.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline import CATEGORICAS, CLAVE, HORIZONTE, NUMERICAS, OBJETIVO, SERIE, YA_LISTAS

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMA = 'PRODUCCION'
PRIMER_LUNES = '2017-06-05'
N_LOTES = 10
DIAS_LOTE = 7
COLUMNAS_X = NUMERICAS + YA_LISTAS + CATEGORICAS + SERIE + ['DATE']     # la firma del modelo (31 columnas)
COLUMNAS_LOTE = ['LOTE', 'FECHA_PREDICCION', 'FECHA_LLEGADA_TARGET', 'DERIVA', 'DEFECTO']
DERIVA_FUENTE = {'lote': 3, 'feature': 'transacciones_lag_16', 'factor': 0.5}
DERIVA_DEMANDA = {'desde_lote': 5, 'factor': 1.5}
# Una fila real del lote DERIVA_FUENTE['lote'] por defecto: (defecto, columna, valor).
FILAS_DEFECTUOSAS = [('campo_faltante', 'DAY_OF_MONTH', None),
                     ('fuera_de_rango', 'nivel_serie_16', 15.0),          # el contrato admite hasta log1p(100.000) ≈ 11,51
                     ('categoria_desconocida', 'FAMILY', 'JUGUETES')]


def calendario_lotes(primer_lunes=PRIMER_LUNES, n_lotes=N_LOTES):
    """Una fila por lote: inicio y fin de la semana, día de la predicción y día en que llega el target."""
    inicio = pd.date_range(primer_lunes, periods=n_lotes, freq=f'{DIAS_LOTE}D')
    calendario = pd.DataFrame({'LOTE': range(1, n_lotes + 1), 'INICIO': inicio,
                               'FIN': inicio + pd.Timedelta(days=DIAS_LOTE - 1)})
    calendario['FECHA_PREDICCION'] = calendario['INICIO'] - pd.Timedelta(days=DIAS_LOTE)
    calendario['FECHA_LLEGADA_TARGET'] = calendario['FIN'] + pd.Timedelta(days=1)
    # Comprobación de la regla de no fuga: el día más tardío del lote mira a t−16, que
    # debe ser anterior a la fecha de la predicción.
    assert (calendario['FIN'] - pd.Timedelta(days=HORIZONTE) < calendario['FECHA_PREDICCION']).all()
    return calendario


def inducir_deriva_demanda(ventas, calendario, desde_lote=DERIVA_DEMANDA['desde_lote'],
                           factor=DERIVA_DEMANDA['factor']):
    """Multiplica la venta real por `factor` desde el lunes del lote `desde_lote`.
    Se aplica a la muestra de la OBT antes de construir_features."""
    inicio = calendario.loc[calendario['LOTE'] == desde_lote, 'INICIO'].iloc[0]
    ventas = ventas.copy()
    ventas.loc[pd.to_datetime(ventas['DATE']) >= inicio, OBJETIVO] *= factor
    return ventas


def inducir_deriva_fuente(lotes, lote=DERIVA_FUENTE['lote'], feature=DERIVA_FUENTE['feature'],
                          factor=DERIVA_FUENTE['factor']):
    """Cambia la escala de `feature` (en log1p) solo en las filas del lote `lote`."""
    lotes = lotes.copy()
    filas = lotes['LOTE'] == lote
    lotes.loc[filas, feature] = np.log1p(np.expm1(lotes.loc[filas, feature]) * factor)
    return lotes


def agregar_filas_defectuosas(lotes, lote=DERIVA_FUENTE['lote'], defectos=FILAS_DEFECTUOSAS):
    """Agrega al lote `lote` una copia de una fila real por cada defecto de `defectos`."""
    del_lote = lotes[lotes['LOTE'] == lote]
    copias = del_lote.sample(len(defectos), random_state=0).copy()
    copias['DAY_OF_MONTH'] = copias['DAY_OF_MONTH'].astype('Int64')
    for i, (defecto, columna, valor) in enumerate(defectos):
        copias.iloc[i, copias.columns.get_loc('DEFECTO')] = defecto
        copias.iloc[i, copias.columns.get_loc(columna)] = pd.NA if valor is None else valor
    lotes = lotes.astype({'DAY_OF_MONTH': 'Int64'})
    return pd.concat([lotes, copias], ignore_index=True).sort_values(['LOTE'] + CLAVE).reset_index(drop=True)


def construir_lotes(datos, calendario, huella_datos):
    """Separa las filas de `datos` (salida de construir_features sobre la venta con la deriva
    de demanda) en lotes y aplica la deriva de la fuente y las filas defectuosas.

    Devuelve dos tablas: `lotes`, con las columnas de la firma y las del lote, sin el
    target; y `target`, con la venta real de las filas válidas y el día en que se conoce."""
    fechas = pd.to_datetime(datos['DATE'])
    partes = []
    for fila in calendario.itertuples(index=False):
        semana = datos.loc[fechas.between(fila.INICIO, fila.FIN)].copy()
        semana['LOTE'] = fila.LOTE
        semana['FECHA_PREDICCION'] = fila.FECHA_PREDICCION
        semana['FECHA_LLEGADA_TARGET'] = fila.FECHA_LLEGADA_TARGET
        partes.append(semana)
    todos = pd.concat(partes, ignore_index=True)
    todos['DERIVA'] = np.select([todos['LOTE'] == DERIVA_FUENTE['lote'],
                                 todos['LOTE'] >= DERIVA_DEMANDA['desde_lote']],
                                ['fuente_transacciones', 'demanda'], 'ninguna')
    todos['DEFECTO'] = None
    todos['HUELLA_DATOS'] = huella_datos
    if todos.duplicated(CLAVE).any():
        raise RuntimeError('Hay filas repetidas por tienda–producto–día.')
    target = todos[['LOTE', 'FECHA_LLEGADA_TARGET'] + CLAVE + [OBJETIVO]].sort_values(['LOTE'] + CLAVE)
    lotes = inducir_deriva_fuente(todos[COLUMNAS_LOTE + COLUMNAS_X + ['HUELLA_DATOS']])
    lotes = agregar_filas_defectuosas(lotes)
    return lotes, target.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Snowflake
# --------------------------------------------------------------------------- #
def crear_tablas():
    from src.datos import conectar
    sql = (RAIZ / 'snowflake' / '30_tablas_produccion.sql').read_text(encoding='utf-8')
    with conectar('PSET4_TABLAS') as con:
        for cursor in con.execute_string(sql, remove_comments=True):
            cursor.close()
        with con.cursor() as cur:
            cur.execute(f'SHOW TABLES IN SCHEMA {ESQUEMA}')
            print('Tablas en', ESQUEMA + ':', [fila[1] for fila in cur.fetchall()])


def subir(tabla, df, con):
    """Reemplaza el contenido de `tabla` por `df` (TRUNCATE + carga), sin tocar su definición."""
    from snowflake.connector.pandas_tools import write_pandas
    df = df.copy()
    df.columns = [c.upper() for c in df.columns]
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.date
    with con.cursor() as cur:
        cur.execute(f'TRUNCATE TABLE {ESQUEMA}.{tabla}')
    ok, _, filas, _ = write_pandas(con, df, tabla, schema=ESQUEMA, quote_identifiers=False)
    if not ok or filas != len(df):
        raise RuntimeError(f'Carga incompleta en {tabla}: {filas} de {len(df)} filas')
    return filas


def leer_lote(lote, con=None):
    """Las filas del lote `lote` tal como las recibe el servicio: las 31 columnas de la firma."""
    from src.datos import conectar
    columnas = ', '.join(c.upper() for c in COLUMNAS_X)
    sql = f'SELECT {columnas} FROM {ESQUEMA}.LOTES WHERE LOTE = %s ORDER BY STORE_NBR, ITEM_NBR, DATE'
    propia = con is None
    con = con or conectar('PSET4_LEER_LOTE')
    try:
        with con.cursor() as cur:
            cur.execute(sql, (int(lote),))
            df = cur.fetch_pandas_all()
    finally:
        if propia:
            con.close()
    return df.rename(columns={c.upper(): c for c in COLUMNAS_X})


def construir():
    from src.datos import cargar_muestra, conectar
    from src.pipeline import construir_features

    ventas, meta = cargar_muestra(extraer_si_falta=False)
    calendario = calendario_lotes()
    datos = construir_features(inducir_deriva_demanda(ventas, calendario))
    lotes, target = construir_lotes(datos, calendario, meta['sha256'])
    print(calendario.assign(filas=lotes.groupby('LOTE').size().to_numpy()).to_string(index=False))
    with conectar('PSET4_SUBIR_LOTES') as con:
        print('LOTES:', subir('LOTES', lotes, con), 'filas')
        print('LOTES_TARGET:', subir('LOTES_TARGET', target, con), 'filas')
    return lotes, target


def resumen():
    from src.datos import consultar
    print(consultar(f"""
        SELECT l.LOTE, MIN(l.DATE) AS INICIO, MAX(l.DATE) AS FIN, ANY_VALUE(l.FECHA_PREDICCION) AS PREDICCION,
               ANY_VALUE(l.FECHA_LLEGADA_TARGET) AS LLEGA_TARGET, ANY_VALUE(l.DERIVA) AS DERIVA, COUNT(l.DEFECTO) AS DEFECTUOSAS,
               COUNT(*) AS FILAS, COUNT(IFF(l.DEFECTO IS NULL, t.UNIT_SALES_TARGET, NULL)) AS CON_TARGET
        FROM {ESQUEMA}.LOTES l
        LEFT JOIN {ESQUEMA}.LOTES_TARGET t USING (STORE_NBR, ITEM_NBR, DATE)
        GROUP BY l.LOTE ORDER BY l.LOTE""", 'PSET4_RESUMEN').to_string(index=False))


if __name__ == '__main__':
    sys.path.insert(0, str(RAIZ))
    orden = sys.argv[1] if len(sys.argv) > 1 else ''
    if orden == 'tablas':
        crear_tablas()
    elif orden == 'construir':
        construir()
    elif orden == 'resumen':
        resumen()
    else:
        print(__doc__)
