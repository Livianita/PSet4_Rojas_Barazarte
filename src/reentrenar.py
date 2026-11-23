"""Entrenamiento y registro del modelo de producción (GB-cuantil 0,75).

    python -m src.reentrenar inicial        # modelo de producción con corte FIN_ENTRENAMIENTO_INICIAL
    python -m src.reentrenar archivos_api   # solo regenera api/contrato.json, respaldo.json y referencia_deriva.json
    python -m src.reentrenar referencia_cv  # media y desviación de la CV del champion (monitoreo/referencia_cv.json)
    MOTIVO="..." python -m src.reentrenar reentrenar <paso> <ejecucion>          # challenger + regla de promoción
    MOTIVO_DECISION="..." python -m src.reentrenar decidir <paso> <si|no>      # decisión humana

Usa la misma preparación de src/pipeline.py y los hiperparámetros del tuning del
PSet 3 (versión 2 del registro), sin repetir el tuning. Cada corrida queda en el
mismo experimento de MLflow con el tag fase, se registra como nueva versión de
favorita-perecederos-modelo y recibe un alias.
"""

import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_pinball_loss
from sklearn.pipeline import Pipeline

from src.negocio import CO, CU, CUANTIL, ReglaRespaldo, resultado_negocio
from src.pipeline import (CATEGORICAS, CLAVE, HORIZONTE, NUMERICAS, OBJETIVO, SERIE, YA_LISTAS, pliegues,
                          preparacion, rmsle)

RAIZ = Path(__file__).resolve().parents[1]
MODELO_REGISTRADO = 'favorita-perecederos-modelo'
VERSION_HIPERPARAMETROS = '2'                 # GB-cuantil del PSet 3 (hiperparámetros del tuning)
FIN_ENTRENAMIENTO_INICIAL = '2017-05-28'      # domingo: desde el lunes 29-05 empiezan los lotes semanales
COLUMNAS_X = NUMERICAS + YA_LISTAS + CATEGORICAS + SERIE + ['DATE']
HIPER = ['learning_rate', 'max_iter', 'max_leaf_nodes', 'min_samples_leaf', 'l2_regularization', 'random_state']
CONFIABLES = ['numpy.dtype', 'sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor']

# Límites físicos del contrato de la API (no son los del entrenamiento: esos los vigila el monitoreo).
LOG_VENTA_MAX = round(float(np.log1p(100_000)), 2)
RANGOS = {**{c: (0.0, LOG_VENTA_MAX) for c in NUMERICAS if c.startswith(('venta_', 'media_', 'nivel_'))},
          'std_28_desde_16': (0.0, 6.0), 'frac_ceros_28_desde_16': (0.0, 1.0),
          'dias_sin_venta_16': (0.0, 90.0), 'transacciones_lag_16': (0.0, 12.0),
          'DAY_OF_MONTH': (1, 31), 'APPLICABLE_EVENT_COUNT': (0, 10)}


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True,
                              cwd=RAIZ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'sin-commit'


def hiperparametros(cliente, version=VERSION_HIPERPARAMETROS):
    """Hiperparámetros del GB-cuantil guardados en una versión del registro (sin repetir el tuning)."""
    import mlflow
    modelo = mlflow.sklearn.load_model(f'models:/{MODELO_REGISTRADO}/{version}')
    params = modelo.named_steps['modelo'].get_params()
    return {k: params[k] for k in HIPER}


def construir_modelo(hiper, cuantil=CUANTIL):
    return Pipeline([('preparar', preparacion()),
                     ('modelo', HistGradientBoostingRegressor(loss='quantile', quantile=cuantil, **hiper))])


def ventana(datos, fin, inicio=None):
    """Filas con target conocido hasta `fin` (y desde `inicio`, si hay ventana móvil)."""
    fechas = pd.to_datetime(datos['DATE'])
    filtro = fechas <= pd.Timestamp(fin)
    if inicio is not None:
        filtro &= fechas >= pd.Timestamp(inicio)
    d = datos.loc[filtro]
    return d[COLUMNAS_X], d[OBJETIVO]


def referencia_cv(X, y, hiper):
    """Pérdida cuantil, RMSLE y costo de negocio por pliegue (5 pliegues de 16 días)."""
    filas = []
    for k, (ent, val) in enumerate(pliegues(X), start=1):
        modelo = construir_modelo(hiper).fit(X.iloc[ent], y.iloc[ent])
        pred = np.clip(modelo.predict(X.iloc[val]), 0, None)
        respaldo = ReglaRespaldo().fit(X.iloc[ent], y.iloc[ent]).predict(X.iloc[val])
        yv = y.iloc[val]
        costo, costo_base = resultado_negocio(yv, pred)['costo'], resultado_negocio(yv, respaldo)['costo']
        perdida = mean_pinball_loss(yv, pred, alpha=CUANTIL)
        filas.append({'pliegue': k, 'perdida_cuantil': perdida, 'venta_media': yv.mean(),
                      'perdida_cuantil_relativa': perdida / yv.mean(),
                      'rmsle': rmsle(yv, pred), 'costo': costo, 'costo_regla': costo_base,
                      'ahorro_vs_regla_pct': 100 * (1 - costo / costo_base)})
        print(f'  pliegue {k}: pérdida cuantil {filas[-1]["perdida_cuantil"]:.4f}, '
              f'ahorro vs regla {filas[-1]["ahorro_vs_regla_pct"]:+.1f} %', flush=True)
    return pd.DataFrame(filas)


def contrato(X):
    """Contrato de entrada de la API: tipos de la firma, rangos físicos y categorías vistas al entrenar."""
    return {
        'numericas': {c: {'min': RANGOS[c][0], 'max': RANGOS[c][1], 'admite_nulo': c not in ('DAY_OF_MONTH',
                                                                                         'APPLICABLE_EVENT_COUNT')}
                      for c in NUMERICAS},
        'ya_listas': YA_LISTAS,
        'categoricas': {c: sorted(X[c].astype(str).unique().tolist(), key=lambda v: (len(v), v))
                        for c in CATEGORICAS},
        'identificadores': {'STORE_NBR': [int(X['STORE_NBR'].min()), int(X['STORE_NBR'].max())]},
    }


def archivos_api(X, y):
    """Escribe en api/ lo que el servicio necesita del entrenamiento: el contrato de
    entrada, la regla de respaldo y la referencia de deriva. Devuelve el contrato."""
    from monitoreo.deriva import RUTA_MUESTRA_REFERENCIA, muestra_referencia, referencia_deriva

    muestra_referencia(X).to_parquet(RUTA_MUESTRA_REFERENCIA, index=False)
    ReglaRespaldo().fit(X, y).guardar(RAIZ / 'api' / 'respaldo.json')
    contrato_api = contrato(X)
    for nombre, contenido in [('contrato.json', contrato_api), ('referencia_deriva.json', referencia_deriva(X))]:
        (RAIZ / 'api' / nombre).write_text(json.dumps(contenido, indent=2, ensure_ascii=False), encoding='utf-8')
    return contrato_api


def registrar(modelo, X, y, hiper, tags, params, metricas, cv, alias, artefactos=None):
    """Registra la corrida en MLflow, crea una versión del modelo y le asigna `alias`."""
    import mlflow
    from mlflow.models import infer_signature
    from mlflow.tracking import MlflowClient

    cliente = MlflowClient()
    ejemplo = X.tail(5).assign(DATE=lambda d: pd.to_datetime(d['DATE']) + pd.Timedelta(days=HORIZONTE))
    with mlflow.start_run(run_name=tags.get('nombre', 'produccion gb cuantil')) as corrida:
        mlflow.set_tags({k: v for k, v in tags.items() if k != 'nombre'})
        mlflow.log_params({**params, **{f'hp_{k}': v for k, v in hiper.items()}})
        mlflow.log_metrics(metricas)
        if cv is not None:
            for _, f in cv.iterrows():
                for m in ['perdida_cuantil', 'rmsle', 'ahorro_vs_regla_pct']:
                    mlflow.log_metric(f'{m}_cv_pliegue', f[m], step=int(f['pliegue']))
            mlflow.log_text(cv.to_csv(index=False), 'cv/pliegues.csv')
        for nombre, contenido in (artefactos or {}).items():
            mlflow.log_text(contenido, nombre)
        info = mlflow.sklearn.log_model(modelo, name='modelo', input_example=ejemplo,
                                        signature=infer_signature(ejemplo, modelo.predict(ejemplo)),
                                        code_paths=[str(RAIZ / 'src')], skops_trusted_types=CONFIABLES)
    version = mlflow.register_model(info.model_uri, MODELO_REGISTRADO,
                                    tags={'rol': alias, 'run_id': corrida.info.run_id, 'modelo': 'gb cuantil',
                                          'cuantil': str(CUANTIL), 'fase': tags.get('fase', ''),
                                          'fin_entrenamiento': params.get('fin_entrenamiento', '')})
    cliente.set_registered_model_alias(MODELO_REGISTRADO, alias, version.version)
    return corrida.info.run_id, version.version


def inicial(fin=FIN_ENTRENAMIENTO_INICIAL):
    """Modelo de producción para la simulación: GB-cuantil con target conocido hasta `fin`."""
    import mlflow
    from mlflow.tracking import MlflowClient
    from dotenv import load_dotenv

    from src.datos import cargar_muestra
    from src.pipeline import construir_features

    load_dotenv(RAIZ / '.env')
    os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')
    mlflow.set_experiment(os.environ.get('MLFLOW_EXPERIMENT_NAME', 'favorita-perecederos'))
    cliente = MlflowClient()

    ventas, meta = cargar_muestra()
    datos = construir_features(ventas)
    X, y = ventana(datos, fin)
    hiper = hiperparametros(cliente)
    print(f'Entrenamiento hasta {fin}: {len(X):,} filas · hiperparámetros de la versión {VERSION_HIPERPARAMETROS}')

    print('Referencia de CV (5 pliegues de 16 días antes del corte):')
    cv = referencia_cv(X, y, hiper)

    inicio = time.perf_counter()
    modelo = construir_modelo(hiper).fit(X, y)
    segundos = time.perf_counter() - inicio
    contrato_api = archivos_api(X, y)

    params = {'tabla_origen': meta['tabla_origen'], 'fecha_corte_snapshot': meta['fecha_corte_snapshot'],
              'huella_datos': meta['sha256'], 'n_series': meta['n_series'], 'fin_entrenamiento': fin,
              'inicio_entrenamiento': str(pd.to_datetime(X['DATE']).min().date()),
              'filas_entrenamiento': len(X), 'cuantil': CUANTIL, 'escenario': f'{CO}:{CU}',
              'hiperparametros_de': f'{MODELO_REGISTRADO}/{VERSION_HIPERPARAMETROS}', 'ventana': 'todo el historico'}
    metricas = {'perdida_cuantil_cv': cv['perdida_cuantil'].mean(),
                'perdida_cuantil_cv_std': cv['perdida_cuantil'].std(ddof=0),
                'rmsle_cv': cv['rmsle'].mean(), 'rmsle_cv_std': cv['rmsle'].std(ddof=0),
                'ahorro_vs_regla_pct_cv': cv['ahorro_vs_regla_pct'].mean(),
                'ahorro_vs_regla_pct_cv_std': cv['ahorro_vs_regla_pct'].std(ddof=0), 'segundos': segundos}
    tags = {'nombre': 'produccion gb cuantil', 'fase': 'produccion', 'rol': 'champion', 'familia': 'boosting',
            'politica': 'directo', 'motivo': 'modelo inicial de la simulacion (corte adelantado, PSet 4)',
            'git_commit': git_commit()}
    run_id, version = registrar(modelo, X, y, hiper, tags, params, metricas, cv, 'champion',
                                artefactos={'api/contrato.json': json.dumps(contrato_api, indent=2),
                                            'api/respaldo.json': (RAIZ / 'api' / 'respaldo.json').read_text()})
    print(f'Registrado {MODELO_REGISTRADO} versión {version} (run {run_id}) con alias champion')
    print(metricas)
    return run_id, version


# --------------------------------------------------------------------------- #
# Reentrenamiento en producción (flujo kestra/reentrenamiento.yml, sección 7.2)
# --------------------------------------------------------------------------- #
PESO_LOTES_PRODUCCION = 3.0     # histórico con mayor peso en los lotes recientes (ver reentrenar_challenger)
N_DESVIACIONES_PROMOCION = 1    # regla de promoción: más de 1 desviación de la CV en el ahorro vs regla


def lotes_etiquetados(fecha, con):
    """Filas válidas de los lotes cuyo target llegó hasta `fecha`, con su target, desde Snowflake."""
    from src.lotes import ESQUEMA

    columnas = ', '.join(f'l.{c.upper()}' for c in COLUMNAS_X)
    with con.cursor() as cur:
        cur.execute(f"""SELECT l.LOTE, {columnas}, t.{OBJETIVO}
                        FROM {ESQUEMA}.LOTES l
                        JOIN {ESQUEMA}.LOTES_TARGET t USING (STORE_NBR, ITEM_NBR, DATE)
                        WHERE l.DEFECTO IS NULL AND t.FECHA_LLEGADA_TARGET <= %s""", (fecha,))
        datos = cur.fetch_pandas_all()
    datos = datos.rename(columns={c.upper(): c for c in COLUMNAS_X})
    return tipos_firma(datos)


def tipos_firma(datos):
    """Los mismos tipos con que el modelo se entrenó (y con que la API le pasa las filas)."""
    datos = datos.copy()
    datos['DATE'] = pd.to_datetime(datos['DATE'])
    for c in CATEGORICAS:
        datos[c] = datos[c].astype(str)
    for c in YA_LISTAS:
        datos[c] = datos[c].astype('int8')
    for c in NUMERICAS:
        datos[c] = datos[c].astype(float)
    return datos


def comparar(modelos, X, y):
    """Pérdida cuantil, pérdida relativa y ahorro frente a la regla de cada modelo, en el mismo lote."""
    regla = ReglaRespaldo.cargar(RAIZ / 'api' / 'respaldo.json').predict(X)
    costo_regla = resultado_negocio(y, regla)['costo']
    resultado = {}
    for nombre, modelo in modelos.items():
        pedido = np.clip(modelo.predict(X), 0, None)
        perdida = mean_pinball_loss(y, pedido, alpha=CUANTIL)
        resultado[nombre] = {'perdida_cuantil': perdida, 'perdida_cuantil_relativa': perdida / float(np.mean(y)),
                             'costo': resultado_negocio(y, pedido)['costo'],
                             'ahorro_vs_regla_pct': 100 * (1 - resultado_negocio(y, pedido)['costo'] / costo_regla)}
    return resultado


def reentrenar_challenger(paso, motivo, ejecucion):
    """Pasos 2 a 7 de la sección 7.2: arma la ventana, reentrena, registra el challenger,
    compara con el champion en el lote etiquetado más reciente y aplica la regla de promoción.

    Ventana: todo el histórico hasta FIN_ENTRENAMIENTO_INICIAL (la OBT) más los lotes de
    producción cuyo target ya llegó, con peso PESO_LOTES_PRODUCCION: los lotes recientes
    describen el régimen actual, y el histórico conserva la estacionalidad del año. El lote
    etiquetado más reciente queda fuera del entrenamiento: es donde se comparan los dos modelos,
    y ninguno de los dos lo vio."""
    import mlflow
    from dotenv import load_dotenv
    from mlflow.tracking import MlflowClient

    from monitoreo.alertas import referencia_cv
    from src.datos import cargar_muestra, conectar
    from src.pipeline import construir_features
    from src.produccion import fecha_del_paso

    load_dotenv(RAIZ / '.env')
    os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')
    mlflow.set_experiment(os.environ.get('MLFLOW_EXPERIMENT_NAME', 'favorita-perecederos'))
    cliente = MlflowClient()
    fecha = fecha_del_paso(paso)

    ventas, meta = cargar_muestra()
    X_hist, y_hist = ventana(construir_features(ventas), FIN_ENTRENAMIENTO_INICIAL)
    with conectar('PSET4_REENTRENAMIENTO') as con:
        etiquetados = lotes_etiquetados(fecha, con)
    if etiquetados.empty:
        raise SystemExit(f'Paso {paso}: todavía no llegó el target de ningún lote.')
    lote_evaluacion = int(etiquetados['LOTE'].max())
    entrena = etiquetados[etiquetados['LOTE'] < lote_evaluacion]
    evalua = etiquetados[etiquetados['LOTE'] == lote_evaluacion]
    lotes_entrenamiento = sorted(int(lote) for lote in entrena['LOTE'].unique())

    X = pd.concat([tipos_firma(X_hist), entrena[COLUMNAS_X]], ignore_index=True)
    y = pd.concat([y_hist, entrena[OBJETIVO]], ignore_index=True)
    pesos = np.r_[np.ones(len(X_hist)), np.full(len(entrena), PESO_LOTES_PRODUCCION)]

    campeon_version = cliente.get_model_version_by_alias(MODELO_REGISTRADO, 'champion')
    campeon = mlflow.sklearn.load_model(f'models:/{MODELO_REGISTRADO}/{campeon_version.version}')
    hiper = {k: campeon.named_steps['modelo'].get_params()[k] for k in HIPER}
    print(f'Paso {paso} ({fecha}): {len(X_hist):,} filas del histórico + lotes {lotes_entrenamiento} '
          f'({len(entrena):,} filas, peso {PESO_LOTES_PRODUCCION}); evaluación en el lote {lote_evaluacion}. '
          f'Hiperparámetros del champion (versión {campeon_version.version}).', flush=True)

    inicio = time.perf_counter()
    challenger = construir_modelo(hiper).fit(X, y, modelo__sample_weight=pesos)
    segundos = time.perf_counter() - inicio

    comparacion = comparar({'champion': campeon, 'challenger': challenger}, evalua[COLUMNAS_X], evalua[OBJETIVO])
    desviacion = referencia_cv()['ahorro_vs_regla_pct']['desviacion']
    diferencia = comparacion['challenger']['ahorro_vs_regla_pct'] - comparacion['champion']['ahorro_vs_regla_pct']
    umbral = N_DESVIACIONES_PROMOCION * desviacion
    recomendacion = 'promover' if diferencia > umbral else 'mantener champion'

    params = {'tabla_origen': meta['tabla_origen'], 'huella_datos': meta['sha256'], 'fin_entrenamiento': str(fecha),
              'ventana': f'historico hasta {FIN_ENTRENAMIENTO_INICIAL} + lotes {lotes_entrenamiento} con peso '
                         f'{PESO_LOTES_PRODUCCION}', 'lotes_entrenamiento': str(lotes_entrenamiento),
              'lote_evaluacion': lote_evaluacion, 'filas_entrenamiento': len(X), 'cuantil': CUANTIL,
              'escenario': f'{CO}:{CU}', 'hiperparametros_de': f'{MODELO_REGISTRADO}/{campeon_version.version}',
              'paso_simulacion': paso}
    metricas = {'segundos': segundos, 'diferencia_ahorro_pp': diferencia, 'umbral_promocion_pp': umbral,
                **{f'{k}_{quien}': v for quien, m in comparacion.items() for k, v in m.items()}}
    tags = {'nombre': f'reentrenamiento paso {paso}', 'fase': 'reentrenamiento', 'rol': 'challenger',
            'familia': 'boosting', 'motivo': motivo, 'recomendacion_regla': recomendacion,
            'champion_comparado': campeon_version.version, 'ejecucion_kestra': ejecucion,
            'git_commit': os.environ.get('GIT_COMMIT', git_commit())}
    run_id, version = registrar(challenger, X, y, hiper, tags, params, metricas, None, 'challenger')

    fila = {'PASO': paso, 'FECHA_PASO': fecha, 'EJECUCION': ejecucion, 'MOTIVO': motivo, 'RUN_ID': run_id,
            'VERSION_CHALLENGER': str(version), 'VERSION_CHAMPION': str(campeon_version.version),
            'LOTES_ENTRENAMIENTO': str(lotes_entrenamiento), 'LOTE_EVALUACION': lote_evaluacion,
            **{f'{k}_{quien}'.upper(): v for quien, m in comparacion.items() for k, v in m.items()},
            'DIFERENCIA_AHORRO_PP': diferencia, 'UMBRAL_PROMOCION_PP': umbral, 'RECOMENDACION': recomendacion,
            'DECISION': 'pendiente'}
    guardar_reentrenamiento(fila)
    resumen = (f'Lote {lote_evaluacion}: ahorro vs regla champion v{campeon_version.version} '
               f'{comparacion["champion"]["ahorro_vs_regla_pct"]:+.2f} %, challenger v{version} '
               f'{comparacion["challenger"]["ahorro_vs_regla_pct"]:+.2f} % (diferencia {diferencia:+.2f} pp, '
               f'umbral {umbral:.2f} pp) → la regla recomienda: {recomendacion}')
    print(resumen)
    print('::' + json.dumps({'outputs': {'version_challenger': str(version), 'run_id': run_id,
                                         'version_champion': str(campeon_version.version),
                                         'recomendacion': recomendacion, 'resumen': resumen}}) + '::')
    return fila


def guardar_reentrenamiento(fila):
    from snowflake.connector.pandas_tools import write_pandas

    from src.datos import conectar
    from src.lotes import ESQUEMA

    with conectar('PSET4_REENTRENAMIENTO') as con, con.cursor() as cur:
        cur.execute(f'DELETE FROM {ESQUEMA}.REENTRENAMIENTOS WHERE PASO = %s', (fila['PASO'],))
        write_pandas(con, pd.DataFrame([fila]), 'REENTRENAMIENTOS', schema=ESQUEMA, quote_identifiers=False)


def decidir(paso, aprobado, motivo_decision):
    """Paso 8 de la sección 7.2: si la persona aprueba, el alias champion pasa al challenger;
    si rechaza, el champion queda intacto. La decisión y su motivo quedan en el registro de
    MLflow (tags de la versión) y en PRODUCCION.REENTRENAMIENTOS."""
    from dotenv import load_dotenv
    from mlflow.tracking import MlflowClient

    from src.datos import conectar
    from src.lotes import ESQUEMA

    load_dotenv(RAIZ / '.env')
    cliente = MlflowClient()
    with conectar('PSET4_DECISION') as con, con.cursor() as cur:
        cur.execute(f'SELECT VERSION_CHALLENGER, VERSION_CHAMPION, RECOMENDACION FROM {ESQUEMA}.REENTRENAMIENTOS '
                    'WHERE PASO = %s', (paso,))
        challenger, campeon, recomendacion = cur.fetchone()
        if aprobado:
            cliente.set_registered_model_alias(MODELO_REGISTRADO, 'champion', challenger)
            decision, final = 'aprobado', challenger
        else:
            decision, final = 'rechazado', campeon
        for clave, valor in {'decision': decision, 'motivo_decision': motivo_decision or '-',
                             'recomendacion_regla': recomendacion}.items():
            cliente.set_model_version_tag(MODELO_REGISTRADO, challenger, clave, valor)
        cur.execute(f"""UPDATE {ESQUEMA}.REENTRENAMIENTOS SET DECISION = %s, MOTIVO_DECISION = %s,
                        VERSION_CHAMPION_FINAL = %s, DECIDIDO_EN = CURRENT_TIMESTAMP() WHERE PASO = %s""",
                    (decision, motivo_decision, final, paso))
    actual = cliente.get_model_version_by_alias(MODELO_REGISTRADO, 'champion').version
    print(f'Paso {paso}: challenger v{challenger} {decision} ({motivo_decision or "sin motivo"}); '
          f'regla: {recomendacion}. champion → versión {actual}.')
    print('::' + json.dumps({'outputs': {'decision': decision, 'champion': str(actual)}}) + '::')


def referencia_cv_monitoreo(fin=FIN_ENTRENAMIENTO_INICIAL):
    """Repite la CV del champion (mismos pliegues e hiperparámetros) y guarda en
    monitoreo/referencia_cv.json la media y la desviación de cada métrica. La pérdida
    relativa (pérdida cuantil / venta media) no depende del volumen: separa un modelo que
    empeora de una demanda que crece."""
    from src.datos import cargar_muestra
    from src.pipeline import construir_features
    import mlflow
    from dotenv import load_dotenv

    load_dotenv(RAIZ / '.env')
    X, y = ventana(construir_features(cargar_muestra()[0]), fin)
    os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')
    try:
        hiper = hiperparametros(None)
    except Exception:  # noqa: BLE001 — sin servidor de MLflow: la copia del champion de las pruebas
        modelo = mlflow.sklearn.load_model(str(RAIZ / 'tests' / 'fixtures' / 'modelo'))
        hiper = {k: modelo.named_steps['modelo'].get_params()[k] for k in HIPER}
    cv = referencia_cv(X, y, hiper)
    metricas = ['perdida_cuantil', 'perdida_cuantil_relativa', 'rmsle', 'ahorro_vs_regla_pct']
    salida = {'fin_entrenamiento': fin, 'pliegues': len(cv),
              **{m: {'media': float(cv[m].mean()), 'desviacion': float(cv[m].std(ddof=0))} for m in metricas},
              'por_pliegue': cv.round(6).to_dict(orient='records')}
    ruta = RAIZ / 'monitoreo' / 'referencia_cv.json'
    ruta.write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({m: salida[m] for m in metricas}, indent=2))


if __name__ == '__main__':
    warnings.filterwarnings('ignore', category=FutureWarning)
    warnings.filterwarnings('ignore', category=UserWarning)
    sys.path.insert(0, str(RAIZ))
    orden = sys.argv[1] if len(sys.argv) > 1 else ''
    if orden == 'inicial':
        inicial(*(sys.argv[2:3]))
    elif orden == 'reentrenar':          # flujo reentrenamiento.yml: paso, ejecución; el motivo va en MOTIVO
        reentrenar_challenger(int(sys.argv[2]), os.environ.get('MOTIVO', 'manual'), sys.argv[3])
    elif orden == 'decidir':             # flujo reentrenamiento.yml: paso, si|no; el motivo va en MOTIVO_DECISION
        decidir(int(sys.argv[2]), sys.argv[3].lower() in ('si', 'sí', 'true', '1'), os.environ.get('MOTIVO_DECISION', ''))
    elif orden == 'referencia_cv':       # media y desviación por pliegue del champion, para el monitoreo
        referencia_cv_monitoreo(*(sys.argv[2:3]))
    elif orden == 'archivos_api':        # regenera api/*.json sin reentrenar
        from src.datos import cargar_muestra
        from src.pipeline import construir_features
        fin = sys.argv[2] if len(sys.argv) > 2 else FIN_ENTRENAMIENTO_INICIAL
        archivos_api(*ventana(construir_features(cargar_muestra()[0]), fin))
        print('api/contrato.json, api/respaldo.json y api/referencia_deriva.json con datos hasta', fin)
    else:
        print(__doc__)
