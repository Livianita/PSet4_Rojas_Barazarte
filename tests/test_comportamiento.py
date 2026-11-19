"""Comportamiento de negocio que el modelo debe cumplir en el dominio de perecederos.

El gradient boosting no garantiza monotonía fila por fila (no se entrenó con
restricciones monótonas), por eso las pruebas exigen la propiedad sobre la muestra
fija de 3.000 filas con un margen pequeño de excepciones, medido al construirlas.
"""

import mlflow
import numpy as np
import pytest

from conftest import FIXTURES, fila_json

HISTORIA = ['venta_lag_16', 'venta_lag_21', 'venta_lag_28', 'venta_lag_35', 'venta_lag_42',
            'media_mismo_dia_4', 'media_7_desde_16', 'media_28_desde_16', 'nivel_serie_16']


@pytest.fixture(scope='module')
def pedir():
    modelo = mlflow.sklearn.load_model(str(FIXTURES / 'modelo'))
    return lambda X: np.clip(modelo.predict(X), 0, None)


def test_mas_ventas_pasadas_no_reducen_el_pedido(pedir, X):
    """Si la tienda vendió el doble de ese producto en las semanas previas, el pedido no baja.
    Medido: baja más de 5 % en 0,3 % de las filas; el total sube ~90 %."""
    base = pedir(X)
    doble = X.copy()
    doble[HISTORIA] = doble[HISTORIA] + np.log(2)          # features en log1p: +log 2 ≈ duplicar
    nuevo = pedir(doble)
    assert np.mean(nuevo < base * 0.95) <= 0.01
    assert nuevo.sum() >= 1.5 * base.sum()


def test_serie_que_dejo_de_vender_recibe_menos(pedir, X):
    """Un producto sin ventas en los últimos 90 días (vistos desde t−16) no debe recibir
    el mismo pedido que cuando vendía: evita merma en productos descontinuados.
    Medido: el pedido total de las series activas cae al ~15 %."""
    base = pedir(X)
    activas = base >= 2
    inactiva = X.copy()
    inactiva[HISTORIA + ['std_28_desde_16']] = 0.0
    inactiva['frac_ceros_28_desde_16'] = 1.0
    inactiva['dias_sin_venta_16'] = 90.0
    nuevo = pedir(inactiva)
    assert nuevo[activas].sum() <= 0.30 * base[activas].sum()
    assert np.mean(nuevo[activas] < base[activas]) >= 0.90


def test_fin_de_semana_pide_mas_que_un_martes(pedir, X):
    """El EDA del PSet 3 mostró más ventas sábado y domingo: el pedido debe seguir ese patrón."""
    def total(dia):
        return pedir(X.assign(DAY_OF_WEEK_ISO=dia)).sum()
    assert total('6') >= 1.05 * total('2')
    assert total('7') >= 1.05 * total('2')


def test_el_pedido_nunca_es_negativo(cliente, pedir, X):
    """El modelo crudo puede devolver valores levemente negativos; la API los lleva a 0."""
    modelo = mlflow.sklearn.load_model(str(FIXTURES / 'modelo'))
    crudo = modelo.predict(X)
    i = int(np.argmin(crudo))
    assert crudo[i] < 0                                      # el caso existe en la muestra
    r = cliente.post('/predecir', json=fila_json(X, i))
    assert r.status_code == 200
    assert r.json()['pedido_sugerido'] == 0 and r.json()['decision'] == 'no reponer'
