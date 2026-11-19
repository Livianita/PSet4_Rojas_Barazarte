"""El contrato del servicio: una entrada válida devuelve 200 con el esquema esperado;
un campo faltante, un tipo incorrecto y una categoría desconocida devuelven 422 con el
campo que falló, sin llegar al modelo. El esquema coincide con la firma de MLflow."""

import typing

import pytest
from mlflow.models import Model

from api.esquemas import ProductoDia
from conftest import FIXTURES, METRICA, PRODUCTO, leer_registro, servicio

CAMPOS_RESPUESTA = {'id_prediccion', 'pedido_sugerido', 'decision', 'version_modelo', 'run_id', 'respaldo',
                    'motivo_respaldo', 'latencia_ms'}


def test_salud_dice_que_version_sirve(cliente):
    respuesta = cliente.get('/salud')
    assert respuesta.status_code == 200
    assert respuesta.json() == {'estado': 'ok', 'modelo_cargado': True, 'version_modelo': METRICA['version'],
                                'modo_respaldo': False, 'detalle': None}


def test_modelo_dice_nombre_version_alias_y_run_id(cliente):
    respuesta = cliente.get('/modelo').json()
    assert respuesta['nombre'] == 'favorita-perecederos-modelo'
    assert (respuesta['version'], respuesta['run_id']) == (METRICA['version'], METRICA['run_id'])


def test_entrada_valida_devuelve_pedido_decision_y_version(cliente):
    respuesta = cliente.post('/predecir', json=PRODUCTO)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == CAMPOS_RESPUESTA
    assert cuerpo['pedido_sugerido'] > 0 and cuerpo['decision'] == 'reponer'
    assert cuerpo['version_modelo'] == METRICA['version'] and cuerpo['respaldo'] is False


def _rechazo(cliente, producto):
    respuesta = cliente.post('/predecir', json=producto)
    assert respuesta.status_code == 422
    return respuesta.json()['campos'][0]


def test_producto_sin_familia_se_rechaza(cliente):
    producto = PRODUCTO.copy()
    producto.pop('FAMILY')
    error = _rechazo(cliente, producto)
    assert (error['campo'], error['tipo']) == ('FAMILY', 'missing')


def test_tipo_incorrecto_se_rechaza(cliente):
    assert _rechazo(cliente, {**PRODUCTO, 'venta_lag_16': 'mucho'})['campo'] == 'venta_lag_16'


def test_categoria_desconocida_se_rechaza(cliente):
    error = _rechazo(cliente, {**PRODUCTO, 'FAMILY': 'BEVERAGES'})         # no es perecedero
    assert (error['campo'], error['valor']) == ('FAMILY', 'BEVERAGES')


@pytest.mark.parametrize('campo, valor', [('frac_ceros_28_desde_16', 1.5), ('DAY_OF_MONTH', 32),
                                          ('IS_HOLIDAY', 2), ('STORE_NBR', 999)])
def test_valor_fuera_de_rango_se_rechaza(cliente, campo, valor):
    assert _rechazo(cliente, {**PRODUCTO, campo: valor})['campo'] == campo


def test_el_target_no_entra(cliente):
    assert _rechazo(cliente, {**PRODUCTO, 'UNIT_SALES_TARGET': 10})['campo'] == 'UNIT_SALES_TARGET'


def test_lote_dice_que_fila_fallo(cliente):
    filas = [PRODUCTO, PRODUCTO, {**PRODUCTO, 'ITEM_CLASS': '9999'}]
    respuesta = cliente.post('/predecir/lote', json={'lote': 'semana-01', 'filas': filas})
    assert respuesta.status_code == 422
    assert respuesta.json()['campos'][0]['campo'] == 'filas[2].ITEM_CLASS'


def test_un_rechazo_no_queda_como_prediccion(cliente):
    cliente.post('/predecir', json={**PRODUCTO, 'FAMILY': 'BEVERAGES'})
    cliente.post('/predecir', json=PRODUCTO)
    assert len(leer_registro(servicio.RUTA_REGISTRO)) == 1


TIPOS_FIRMA = {'double': float, 'integer': int, 'string': str, 'datetime': 'date'}


def _tipo_base(anotacion):
    """Tipo Python de una anotación de Pydantic (sin Optional, Annotated ni Literal)."""
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
    assert [c['name'] for c in firma] == list(ProductoDia.model_fields)
    for columna in firma:
        tipo, esperado = _tipo_base(ProductoDia.model_fields[columna['name']].annotation), TIPOS_FIRMA[columna['type']]
        assert (tipo.__name__ == esperado) if isinstance(esperado, str) else tipo is esperado, columna
