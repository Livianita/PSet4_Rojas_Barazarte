"""Contrato de la API: una entrada válida devuelve 200 con el esquema esperado; un campo
faltante, un tipo incorrecto y una categoría desconocida devuelven 422 nombrando el campo.
También se comprueba que el esquema Pydantic coincide con la firma registrada en MLflow."""

import typing

import pytest
from mlflow.models import Model

from api.esquemas import Entrada
from conftest import FIXTURES, METRICA, fila_json

CAMPOS_RESPUESTA = {'id_prediccion', 'pedido_sugerido', 'decision', 'version_modelo', 'alias', 'run_id',
                    'respaldo', 'motivo_respaldo', 'latencia_ms'}


def test_entrada_valida_devuelve_200(cliente, X):
    r = cliente.post('/predecir', json=fila_json(X))
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == CAMPOS_RESPUESTA
    assert cuerpo['decision'] in ('reponer', 'no reponer')
    assert cuerpo['pedido_sugerido'] >= 0
    assert cuerpo['version_modelo'] == METRICA['version'] and cuerpo['run_id'] == METRICA['run_id']
    assert cuerpo['respaldo'] is False and len(cuerpo['id_prediccion']) == 32


def _error(cliente, cuerpo):
    r = cliente.post('/predecir', json=cuerpo)
    assert r.status_code == 422
    return r.json()


def test_campo_faltante_devuelve_422(cliente, X):
    cuerpo = fila_json(X)
    del cuerpo['FAMILY']
    error = _error(cliente, cuerpo)
    assert error['campos'][0]['campo'] == 'FAMILY' and error['campos'][0]['tipo'] == 'missing'


def test_tipo_incorrecto_devuelve_422(cliente, X):
    error = _error(cliente, {**fila_json(X), 'venta_lag_16': 'mucho'})
    assert error['campos'][0]['campo'] == 'venta_lag_16'


def test_categoria_desconocida_devuelve_422(cliente, X):
    error = _error(cliente, {**fila_json(X), 'FAMILY': 'BEVERAGES'})      # no es perecedero
    assert error['campos'][0]['campo'] == 'FAMILY' and 'BEVERAGES' == error['campos'][0]['valor']


@pytest.mark.parametrize('campo, valor', [('frac_ceros_28_desde_16', 1.5), ('DAY_OF_MONTH', 32),
                                          ('IS_HOLIDAY', 2), ('STORE_NBR', 999)])
def test_fuera_de_rango_devuelve_422(cliente, X, campo, valor):
    error = _error(cliente, {**fila_json(X), campo: valor})
    assert error['campos'][0]['campo'] == campo


def test_campo_extra_devuelve_422(cliente, X):
    error = _error(cliente, {**fila_json(X), 'UNIT_SALES_TARGET': 10})    # el target nunca entra
    assert error['campos'][0]['campo'] == 'UNIT_SALES_TARGET'


def test_lote_indica_la_fila_que_fallo(cliente, X):
    filas = [fila_json(X, i) for i in range(3)]
    filas[2]['ITEM_CLASS'] = '9999'
    r = cliente.post('/predecir/lote', json={'lote': 'prueba', 'filas': filas})
    assert r.status_code == 422 and r.json()['campos'][0]['campo'] == 'filas[2].ITEM_CLASS'


TIPOS_FIRMA = {'double': float, 'integer': int, 'string': str, 'datetime': 'date'}


def _tipo_base(anotacion):
    """Tipo Python de una anotación de Pydantic (quita Optional / Annotated / Literal)."""
    origen = typing.get_origin(anotacion)
    if origen is typing.Annotated:
        return _tipo_base(typing.get_args(anotacion)[0])
    if origen is typing.Union:
        return _tipo_base(next(a for a in typing.get_args(anotacion) if a is not type(None)))
    if origen is typing.Literal:
        return type(typing.get_args(anotacion)[0])
    return anotacion


def test_esquema_coincide_con_la_firma_de_mlflow():
    firma = Model.load(str(FIXTURES / 'modelo')).signature.inputs.to_dict()
    assert [c['name'] for c in firma] == list(Entrada.model_fields)
    for columna in firma:
        tipo = _tipo_base(Entrada.model_fields[columna['name']].annotation)
        esperado = TIPOS_FIRMA[columna['type']]
        assert (tipo.__name__ == esperado) if isinstance(esperado, str) else tipo is esperado, columna
