"""El modelo exportado reproduce la métrica registrada en MLflow sobre la muestra fija.

Tolerancia: 0,1 % relativo. El mismo artefacto con las mismas versiones de las
librerías da el mismo número hasta ~1e-12; la tolerancia solo deja pasar diferencias
numéricas de plataforma (Windows al registrar, Linux en CI). Cualquier cambio real
—otro modelo, otra preparación, otra versión de scikit-learn— mueve la pérdida en
varios puntos porcentuales: la diferencia entre los pliegues de la CV es de ~4 %.
"""

import mlflow
import numpy as np
import pytest
from sklearn.metrics import mean_pinball_loss

from conftest import FIXTURES, METRICA

TOLERANCIA_RELATIVA = 1e-3


@pytest.fixture(scope='module')
def modelo():
    return mlflow.sklearn.load_model(str(FIXTURES / 'modelo'))


def test_reproduce_la_metrica_registrada(modelo, muestra, X):
    pred = np.clip(modelo.predict(X), 0, None)
    perdida = mean_pinball_loss(muestra['UNIT_SALES_TARGET'], pred, alpha=METRICA['cuantil'])
    assert perdida == pytest.approx(METRICA['valor'], rel=TOLERANCIA_RELATIVA)


def test_es_el_cuantil_del_escenario_principal(modelo):
    """Co:Cu = 1:3 → q = 3 / (3 + 1) = 0,75 (regla de pedido del PSet 3)."""
    gb = modelo.named_steps['modelo']
    assert gb.loss == 'quantile' and gb.quantile == pytest.approx(0.75) == METRICA['cuantil']


def test_cobertura_cercana_al_cuantil(modelo, muestra, X):
    """Si el pedido es el cuantil 0,75, cerca del 75 % de los días la venta no lo supera."""
    pred = np.clip(modelo.predict(X), 0, None)
    cubiertos = np.mean(muestra['UNIT_SALES_TARGET'].to_numpy() <= pred)
    assert 0.65 <= cubiertos <= 0.90
