"""Lo que comparten las pruebas. Se corren desde proyecto_final/ con:

    pytest -v

Las pruebas no usan el registro de MLflow ni Snowflake: CARGAR_MODELO=no evita que
el servicio busque el modelo al importarse (en GitHub Actions no hay servidor de
MLflow), y cada prueba pone el modelo exportado en tests/fixtures/modelo con
mlflow.sklearn.save_model, y un registro temporal (tmp_path).
"""

import json
import os
import sys
from pathlib import Path

os.environ['CARGAR_MODELO'] = 'no'
os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')

import mlflow.sklearn  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / 'tests' / 'fixtures'
sys.path.insert(0, str(RAIZ))

from api import main as servicio  # noqa: E402

METRICA = json.loads((FIXTURES / 'metrica_registrada.json').read_text(encoding='utf-8'))
TOKEN = 'token-de-prueba'

# Un producto escrito a mano: leche (DAIRY) en la tienda 44, un lunes de junio.
PRODUCTO = {
    'venta_lag_16': 1.79, 'venta_lag_21': 2.08, 'venta_lag_28': 1.61, 'venta_lag_35': 1.95, 'venta_lag_42': 2.2,
    'media_mismo_dia_4': 1.96, 'media_7_desde_16': 1.85, 'media_28_desde_16': 1.88, 'std_28_desde_16': 0.41,
    'frac_ceros_28_desde_16': 0.0, 'dias_sin_venta_16': 0, 'nivel_serie_16': 1.9, 'transacciones_lag_16': 7.4,
    'DAY_OF_MONTH': 12, 'APPLICABLE_EVENT_COUNT': 0, 'IS_PAYDAY_PROXY': 0, 'IS_MONTH_END': 0, 'IS_HOLIDAY': 0,
    'IS_TRANSFER_DAY': 0, 'IS_ADDITIONAL_DAY': 0, 'IS_BRIDGE_DAY': 0, 'IS_WORK_DAY': 1, 'HAS_SPECIAL_EVENT': 0,
    'DAY_OF_WEEK_ISO': '1', 'FAMILY': 'DAIRY', 'ITEM_CLASS': '2112', 'STORE_TYPE': 'D', 'STORE_CLUSTER': '13',
    'STORE_NBR': 44, 'ITEM_NBR': 1473474, 'DATE': '2017-06-12',
}


@pytest.fixture(scope='session')
def modelo_exportado():
    return mlflow.sklearn.load_model(str(FIXTURES / 'modelo'))


@pytest.fixture(scope='session')
def muestra():
    return pd.read_parquet(FIXTURES / 'muestra_fija.parquet')


@pytest.fixture(scope='session')
def X(muestra):
    return muestra.drop(columns='UNIT_SALES_TARGET')


def producto_de(X, i=0):
    """Fila i de la muestra como el JSON que recibe la API (NaN → null, fecha ISO)."""
    fila = X.iloc[i].to_dict()
    fila['DATE'] = str(pd.Timestamp(fila['DATE']).date())
    return {k: (None if isinstance(v, float) and pd.isna(v) else (v.item() if hasattr(v, 'item') else v))
            for k, v in fila.items()}


@pytest.fixture
def cliente(tmp_path, monkeypatch, modelo_exportado):
    """El servicio con el modelo exportado, la versión registrada y registros temporales."""
    monkeypatch.setenv('API_TOKEN_ADMIN', TOKEN)
    servicio.modelo = modelo_exportado
    servicio.version_modelo = METRICA['version']
    servicio.run_id_modelo = METRICA['run_id']
    servicio.error_carga = None
    servicio.modo_respaldo, servicio.motivo_interruptor = False, None
    servicio.RUTA_REGISTRO = str(tmp_path / 'predicciones.jsonl')
    servicio.RUTA_SOLICITUDES = str(tmp_path / 'solicitudes.jsonl')
    servicio.metricas = servicio.Metricas()
    servicio.monitor.filas = []
    return TestClient(servicio.app)


def leer_registro(ruta):
    with open(ruta, encoding='utf-8') as archivo:
        return [json.loads(linea) for linea in archivo]
