"""Exporta a docs/ los CSV que pide la sección 10 del PSet 4.

    python -m src.exportar                 # escribe en docs/
    python -m src.exportar <carpeta>       # en otra carpeta

En Docker (Kestra tiene la conexión a Snowflake y a MLflow):

    docker compose exec -T -w /workspace kestra /opt/proyecto-venv/bin/python -m src.exportar

Archivos:
    predicciones.csv      PRODUCCION.PREDICCIONES, sin la columna ENTRADAS (ver abajo)
    monitoreo.csv         PRODUCCION.MONITOREO, una fila por lote
    alertas.csv           PRODUCCION.ALERTAS, una fila por alerta disparada
    corridas.csv          todas las corridas del experimento (mlflow.search_runs)
    reentrenamientos.csv  las corridas con fase='reentrenamiento', unidas a la decisión
                          registrada en PRODUCCION.REENTRENAMIENTOS
    solicitudes.csv       registro de solicitudes de la API (una fila por petición HTTP): de
                          aquí salen la latencia y las tasas de error de MONITOREO

ENTRADAS (las 31 features de cada predicción, en JSON) suma más de 120 MB y supera el
límite de GitHub. Las mismas entradas están en PRODUCCION.LOTES con la clave
(LOTE, STORE_NBR, ITEM_NBR, DATE), que sí viaja en predicciones.csv.
"""

import os
import sys
from pathlib import Path

import pandas as pd

from src.datos import conectar
from src.lotes import ESQUEMA

RAIZ = Path(__file__).resolve().parents[1]
EXPERIMENTO = os.environ.get('MLFLOW_EXPERIMENT_NAME', 'favorita-perecederos')
RUTA_SOLICITUDES = os.environ.get('RUTA_SOLICITUDES', '/registros/solicitudes.jsonl')

COLUMNAS_PREDICCIONES = ['ID_PREDICCION', 'FECHA_HORA', 'LOTE', 'EJECUCION', 'STORE_NBR', 'ITEM_NBR', 'DATE',
                         'PEDIDO', 'DECISION', 'VERSION_MODELO', 'RUN_ID', 'MODELO', 'ALIAS', 'USO_RESPALDO',
                         'MOTIVO_RESPALDO', 'LATENCIA_MS']


def leer(sql, con):
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetch_pandas_all()


def tablas_produccion(con):
    predicciones = leer(f'SELECT {", ".join(COLUMNAS_PREDICCIONES)} FROM {ESQUEMA}.PREDICCIONES '
                        'ORDER BY LOTE, STORE_NBR, ITEM_NBR, DATE', con)
    monitoreo = leer(f'SELECT * FROM {ESQUEMA}.MONITOREO ORDER BY LOTE', con)
    alertas = leer(f'SELECT * FROM {ESQUEMA}.ALERTAS ORDER BY PASO, LOTE, ALERTA', con)
    decisiones = leer(f'SELECT * FROM {ESQUEMA}.REENTRENAMIENTOS ORDER BY PASO', con)
    return predicciones, monitoreo, alertas, decisiones


def corridas_mlflow():
    import mlflow

    corridas = mlflow.search_runs(experiment_names=[EXPERIMENTO], output_format='pandas')
    corridas = corridas.sort_values('start_time').reset_index(drop=True)
    fase = corridas['tags.fase'] if 'tags.fase' in corridas else pd.Series('', index=corridas.index)
    reentrenamientos = corridas[fase == 'reentrenamiento'].reset_index(drop=True)
    # Versión registrada por cada corrida y los tags de su decisión (incluye las versiones
    # descartadas de corridas que no llegaron a la pausa de aprobación).
    cliente = mlflow.MlflowClient()
    versiones = []
    for run_id in reentrenamientos['run_id']:
        for version in cliente.search_model_versions(f"run_id = '{run_id}'"):
            versiones.append({'run_id': run_id, 'version.modelo': version.version,
                              'version.decision': version.tags.get('decision'),
                              'version.motivo_decision': version.tags.get('motivo_decision')})
    if versiones:
        reentrenamientos = reentrenamientos.merge(pd.DataFrame(versiones), on='run_id', how='left')
    return corridas, reentrenamientos


def solicitudes_api(ruta=RUTA_SOLICITUDES):
    """El registro de solicitudes de la API (volumen compartido con Kestra), si existe."""
    if not Path(ruta).exists():
        return None
    return pd.read_json(ruta, lines=True)


def exportar(carpeta=RAIZ / 'docs'):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    with conectar('PSET4_EXPORTAR') as con:
        predicciones, monitoreo, alertas, decisiones = tablas_produccion(con)
    corridas, reentrenamientos = corridas_mlflow()
    # La decisión humana vive en Snowflake; se agrega a cada corrida por su run_id.
    reentrenamientos = reentrenamientos.merge(
        decisiones.rename(columns=lambda c: 'decision.' + c.lower()),
        left_on='run_id', right_on='decision.run_id', how='left').drop(columns='decision.run_id')

    archivos = {'predicciones.csv': predicciones, 'monitoreo.csv': monitoreo, 'alertas.csv': alertas,
                'corridas.csv': corridas, 'reentrenamientos.csv': reentrenamientos}
    solicitudes = solicitudes_api()
    if solicitudes is not None:
        archivos['solicitudes.csv'] = solicitudes
    for nombre, tabla in archivos.items():
        tabla.to_csv(carpeta / nombre, index=False, encoding='utf-8-sig')   # Excel lee bien las tildes
        print(f'{nombre}: {len(tabla):,} filas, {(carpeta / nombre).stat().st_size / 1e6:.1f} MB')


if __name__ == '__main__':
    exportar(*sys.argv[1:2])
