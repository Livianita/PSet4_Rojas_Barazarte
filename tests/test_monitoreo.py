"""Instrumentación del servicio: cada predicción queda registrada con lo necesario para
unirla después con la venta real, /metricas separa los errores de validación de los de
servidor, y la alerta de /deriva se enciende con una ventana alejada de la referencia."""

from conftest import METRICA, PRODUCTO, leer_registro, servicio
from monitoreo.deriva import psi


def test_cada_prediccion_queda_registrada(cliente):
    respuesta = cliente.post('/predecir/lote', json={'lote': 'semana-01', 'filas': [PRODUCTO, PRODUCTO]}).json()
    lineas = leer_registro(servicio.RUTA_REGISTRO)
    assert len(lineas) == 2
    assert lineas[0]['id_prediccion'] == respuesta['predicciones'][0]['id_prediccion']
    assert lineas[0]['version_modelo'] == METRICA['version'] and lineas[0]['run_id'] == METRICA['run_id']
    assert lineas[0]['lote'] == 'semana-01' and lineas[0]['latencia_ms'] >= 0
    # lo que hace falta para unir la predicción con la venta real: tienda, producto y fecha
    assert {k: lineas[0]['entrada'][k] for k in ('STORE_NBR', 'ITEM_NBR', 'DATE')} == \
        {'STORE_NBR': 44, 'ITEM_NBR': 1473474, 'DATE': '2017-06-12'}


def test_metricas_cuentan_peticiones_y_errores(cliente):
    cliente.post('/predecir', json=PRODUCTO)
    cliente.post('/predecir', json={'FAMILY': 'DAIRY'})
    resumen = cliente.get('/metricas').json()
    assert resumen['peticiones'] == 2
    assert resumen['errores_validacion'] == 1 and resumen['errores_cliente'] == 1
    assert resumen['errores_servidor'] == 0
    assert resumen['latencia_p95_ms'] > 0
    assert len(leer_registro(servicio.RUTA_SOLICITUDES)) == 2


def test_un_lote_rechazado_queda_atribuido_a_su_lote(cliente):
    invalido = {**PRODUCTO, 'FAMILY': 'JUGUETES'}
    respuesta = cliente.post('/predecir/lote', json={'lote': 'lote-3-prueba', 'filas': [PRODUCTO, invalido]})
    assert respuesta.status_code == 422 and 'filas[1].FAMILY' in respuesta.json()['error']
    solicitud = leer_registro(servicio.RUTA_SOLICITUDES)[-1]
    assert solicitud['codigo'] == 422 and solicitud['lote'] == 'lote-3-prueba'


def test_psi_es_cero_si_las_distribuciones_son_iguales():
    assert psi([0.5, 0.5], [0.5, 0.5]) == 0
    assert psi([0.5, 0.5], [0.9, 0.1]) > 0.25


def test_la_alerta_de_deriva_se_enciende_con_una_ventana_alejada(cliente):
    servicio.monitor.ventana = 50
    for _ in range(50):
        cliente.post('/predecir', json=PRODUCTO)          # 50 veces el mismo producto: nada se parece
    estado = cliente.get('/deriva').json()
    assert estado['filas_en_ventana'] == 50 and estado['alerta'] is True
    assert estado['psi']['FAMILY'] > estado['umbral']
    servicio.monitor.ventana = 14_000
