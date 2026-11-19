"""Entrenamiento y registro del modelo de producción (GB-cuantil 0,75).

    python -m src.reentrenar inicial        # modelo de producción con corte FIN_ENTRENAMIENTO_INICIAL

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
        filas.append({'pliegue': k, 'perdida_cuantil': mean_pinball_loss(yv, pred, alpha=CUANTIL),
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
    respaldo = ReglaRespaldo().fit(X, y)
    respaldo.guardar(RAIZ / 'api' / 'respaldo.json')
    contrato_api = contrato(X)
    (RAIZ / 'api' / 'contrato.json').write_text(json.dumps(contrato_api, indent=2, ensure_ascii=False),
                                               encoding='utf-8')

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


if __name__ == '__main__':
    warnings.filterwarnings('ignore', category=FutureWarning)
    warnings.filterwarnings('ignore', category=UserWarning)
    sys.path.insert(0, str(RAIZ))
    orden = sys.argv[1] if len(sys.argv) > 1 else ''
    if orden == 'inicial':
        inicial(*(sys.argv[2:3]))
    else:
        print(__doc__)
