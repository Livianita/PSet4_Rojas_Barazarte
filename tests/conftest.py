"""Fixtures compartidos. Las pruebas no necesitan MLflow ni Snowflake: el modelo
viene de tests/fixtures/modelo (exportado con mlflow.sklearn.save_model)."""

import importlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / 'tests' / 'fixtures'
sys.path.insert(0, str(RAIZ))
os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')

METRICA = json.loads((FIXTURES / 'metrica_registrada.json').read_text(encoding='utf-8'))
TOKEN = 'token-de-prueba'


@pytest.fixture(scope='session')
def muestra():
    return pd.read_parquet(FIXTURES / 'muestra_fija.parquet')


@pytest.fixture(scope='session')
def X(muestra):
    return muestra.drop(columns='UNIT_SALES_TARGET')


def fila_json(X, i=0):
    """Fila i de la muestra como el JSON que recibe la API (NaN → null, fecha ISO)."""
    fila = X.iloc[i].to_dict()
    fila['DATE'] = str(pd.Timestamp(fila['DATE']).date())
    return {k: (None if isinstance(v, float) and pd.isna(v) else (v.item() if hasattr(v, 'item') else v))
            for k, v in fila.items()}


@pytest.fixture
def crear_cliente(monkeypatch, tmp_path):
    """Levanta la API con las variables de entorno dadas (recarga el módulo para que las lea)."""
    from fastapi.testclient import TestClient

    clientes = []

    def _crear(**env):
        base = {'MODELO_URI': str(FIXTURES / 'modelo'), 'MODELO_VERSION_LOCAL': METRICA['version'],
                'MODELO_RUN_ID_LOCAL': METRICA['run_id'], 'MODO_RESPALDO': 'false',
                'API_TOKEN_ADMIN': TOKEN, 'RUTA_REGISTRO': str(tmp_path / 'api.db')}
        for k, v in {**base, **env}.items():
            monkeypatch.setenv(k, v)
        import api.main
        modulo = importlib.reload(api.main)
        cliente = TestClient(modulo.app)
        cliente.__enter__()            # ejecuta el arranque (carga del modelo)
        clientes.append(cliente)
        return cliente

    yield _crear
    for c in clientes:
        c.__exit__(None, None, None)


@pytest.fixture
def cliente(crear_cliente):
    return crear_cliente()
