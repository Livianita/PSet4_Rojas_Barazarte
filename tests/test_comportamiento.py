"""Comportamiento de negocio que el modelo debe cumplir con perecederos.

El gradient boosting no garantiza monotonía fila por fila (no se entrenó con
restricciones monótonas), por eso las pruebas exigen la propiedad sobre la muestra
fija de 3.000 filas, con el margen de excepciones que se midió al construirlas.
"""

import numpy as np
import pytest

from conftest import producto_de

HISTORIA = ['venta_lag_16', 'venta_lag_21', 'venta_lag_28', 'venta_lag_35', 'venta_lag_42',
            'media_mismo_dia_4', 'media_7_desde_16', 'media_28_desde_16', 'nivel_serie_16']


@pytest.fixture(scope='module')
def pedir(modelo_exportado):
    return lambda X: np.clip(modelo_exportado.predict(X), 0, None)


def test_mas_ventas_pasadas_no_reducen_el_pedido(pedir, X):
    """Si la tienda vendió el doble de ese producto en las semanas previas, el pedido no baja.
    Medido: baja más de 5 % en 0,3 % de las filas; el total sube ~90 %."""
    base = pedir(X)
    doble = X.copy()
    doble[HISTORIA] = doble[HISTORIA] + np.log(2)          # features en log1p: + log 2 ≈ duplicar
    nuevo = pedir(doble)
    assert np.mean(nuevo < base * 0.95) <= 0.01
    assert nuevo.sum() >= 1.5 * base.sum()


def test_producto_que_dejo_de_venderse_recibe_menos(pedir, X):
    """Un producto sin ventas en los últimos 90 días (vistos desde t−16) no recibe el
    mismo pedido que cuando vendía: así no se acumula merma de productos descontinuados.
    Medido: el pedido total de los productos activos cae al ~15 %."""
    base = pedir(X)
    activos = base >= 2
    sin_ventas = X.copy()
    sin_ventas[HISTORIA + ['std_28_desde_16']] = 0.0
    sin_ventas['frac_ceros_28_desde_16'] = 1.0
    sin_ventas['dias_sin_venta_16'] = 90.0
    nuevo = pedir(sin_ventas)
    assert nuevo[activos].sum() <= 0.30 * base[activos].sum()
    assert np.mean(nuevo[activos] < base[activos]) >= 0.90


def test_fin_de_semana_pide_mas_que_un_martes(pedir, X):
    """El EDA del PSet 3 mostró más ventas el sábado y el domingo: el pedido sigue ese patrón."""
    def total(dia):
        return pedir(X.assign(DAY_OF_WEEK_ISO=dia)).sum()
    assert total('6') >= 1.05 * total('2')
    assert total('7') >= 1.05 * total('2')


def test_el_pedido_nunca_es_negativo(cliente, modelo_exportado, X):
    """El modelo crudo puede devolver valores levemente negativos; el servicio los lleva a 0."""
    crudo = modelo_exportado.predict(X)
    i = int(np.argmin(crudo))
    assert crudo[i] < 0                                      # el caso existe en la muestra
    respuesta = cliente.post('/predecir', json=producto_de(X, i)).json()
    assert respuesta['pedido_sugerido'] == 0 and respuesta['decision'] == 'no reponer'
