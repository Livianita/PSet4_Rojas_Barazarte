"""Respaldo: si el modelo no carga, la API responde con la línea base de negocio
(media de 28 días + stock de seguridad por familia) e indica que usó el respaldo.
El interruptor (variable de entorno o endpoint protegido) fuerza la misma regla."""

import numpy as np
import pandas as pd
import pytest

from conftest import RAIZ, TOKEN, fila_json
from src.negocio import ReglaRespaldo


def _regla(X, i=0):
    return float(ReglaRespaldo.cargar(RAIZ / 'api' / 'respaldo.json').predict(X.iloc[[i]])[0])


def test_modelo_que_no_carga_responde_con_la_regla(crear_cliente, X):
    cliente = crear_cliente(MODELO_URI=str(RAIZ / 'tests' / 'fixtures' / 'no_existe'))
    salud = cliente.get('/salud').json()
    assert salud == {**salud, 'estado': 'degradado', 'modelo_cargado': False}
    r = cliente.post('/predecir', json=fila_json(X))
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo['respaldo'] is True and 'modelo no disponible' in cuerpo['motivo_respaldo']
    assert cuerpo['version_modelo'] is None
    assert cuerpo['pedido_sugerido'] == pytest.approx(_regla(X), abs=1e-3)


def test_interruptor_por_variable_de_entorno(crear_cliente, X):
    cliente = crear_cliente(MODO_RESPALDO='true')
    assert cliente.get('/salud').json()['modo_respaldo'] is True
    cuerpo = cliente.post('/predecir', json=fila_json(X)).json()
    assert cuerpo['respaldo'] is True and cuerpo['pedido_sugerido'] == pytest.approx(_regla(X), abs=1e-3)


def test_interruptor_por_endpoint_protegido(cliente, X):
    assert cliente.post('/respaldo', json={'activo': True}).status_code == 401
    assert cliente.post('/respaldo', json={'activo': True}, headers={'X-Token-Admin': 'otro'}).status_code == 401
    r = cliente.post('/respaldo', json={'activo': True, 'motivo': 'prueba'}, headers={'X-Token-Admin': TOKEN})
    assert r.status_code == 200 and r.json()['modo_respaldo'] is True
    assert cliente.post('/predecir', json=fila_json(X)).json()['respaldo'] is True
    cliente.post('/respaldo', json={'activo': False}, headers={'X-Token-Admin': TOKEN})
    assert cliente.post('/predecir', json=fila_json(X)).json()['respaldo'] is False


def test_regla_de_respaldo_es_la_media_28_mas_ss(X):
    regla = ReglaRespaldo.cargar(RAIZ / 'api' / 'respaldo.json')
    fila = X.iloc[[0]]
    esperado = max(0.0, float(np.expm1(fila['media_28_desde_16'].iloc[0]))
                   + regla.ss_por_familia[fila['FAMILY'].iloc[0]])
    assert regla.predict(fila)[0] == pytest.approx(esperado)


def test_cada_prediccion_queda_registrada(cliente, X, tmp_path):
    import sqlite3
    cliente.post('/predecir/lote', json={'lote': 'L1', 'filas': [fila_json(X, i) for i in range(5)]})
    with sqlite3.connect(tmp_path / 'api.db') as c:
        filas = pd.read_sql('select * from predicciones', c)
        solicitudes = pd.read_sql('select * from solicitudes', c)
    assert len(filas) == 5 and filas['id_prediccion'].is_unique
    assert filas[['ts_utc', 'entradas', 'pedido_sugerido', 'modelo_version', 'run_id', 'latencia_ms']].notna().all().all()
    assert (filas['lote'] == 'L1').all()
    assert solicitudes.iloc[-1][['ruta', 'estado', 'filas']].tolist() == ['/predecir/lote', 200, 5]
