"""Respaldo: si el modelo no carga, el servicio responde con la línea base de negocio
(media de 28 días + stock de seguridad por familia) e indica que usó el respaldo.
El interruptor (variable de entorno o ruta protegida) fuerza la misma regla."""

import importlib

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import PRODUCTO, RAIZ, TOKEN, leer_registro, servicio
from src.negocio import ReglaRespaldo

REGLA = ReglaRespaldo.cargar(RAIZ / 'api' / 'respaldo.json')


def regla_de(producto):
    return float(REGLA.predict(pd.DataFrame([producto]))[0])


def test_si_el_modelo_no_carga_responde_la_regla(cliente):
    servicio.modelo, servicio.version_modelo = None, None
    servicio.error_carga = 'OSError: no existe el modelo'
    assert cliente.get('/salud').json()['estado'] == 'degradado'
    respuesta = cliente.post('/predecir', json=PRODUCTO)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo['respaldo'] is True and 'modelo no disponible' in cuerpo['motivo_respaldo']
    assert cuerpo['version_modelo'] is None
    assert cuerpo['pedido_sugerido'] == pytest.approx(regla_de(PRODUCTO), abs=1e-3)


def test_si_falla_la_carga_al_arrancar_el_servicio_sigue_en_pie(monkeypatch, tmp_path):
    monkeypatch.setenv('CARGAR_MODELO', 'si')
    monkeypatch.setenv('MODELO_URI', str(tmp_path / 'no_existe'))
    monkeypatch.setenv('RUTA_REGISTRO', str(tmp_path / 'p.jsonl'))
    monkeypatch.setenv('RUTA_SOLICITUDES', str(tmp_path / 's.jsonl'))
    try:
        recargado = importlib.reload(servicio)
        salud = TestClient(recargado.app).get('/salud').json()
        assert salud['modelo_cargado'] is False and salud['detalle']
    finally:
        monkeypatch.setenv('CARGAR_MODELO', 'no')
        monkeypatch.delenv('MODELO_URI')
        importlib.reload(servicio)


def test_interruptor_por_variable_de_entorno(monkeypatch, tmp_path):
    monkeypatch.setenv('MODO_RESPALDO', 'true')
    try:
        recargado = importlib.reload(servicio)
        assert recargado.modo_respaldo is True
        recargado.RUTA_REGISTRO = str(tmp_path / 'p.jsonl')
        recargado.RUTA_SOLICITUDES = str(tmp_path / 's.jsonl')
        assert TestClient(recargado.app).post('/predecir', json=PRODUCTO).json()['respaldo'] is True
    finally:
        monkeypatch.delenv('MODO_RESPALDO')
        importlib.reload(servicio)


def test_interruptor_por_ruta_protegida(cliente):
    assert cliente.post('/respaldo', json={'activo': True}).status_code == 401
    assert cliente.post('/respaldo', json={'activo': True}, headers={'X-Token-Admin': 'otro'}).status_code == 401
    encendido = cliente.post('/respaldo', json={'activo': True, 'motivo': 'prueba'}, headers={'X-Token-Admin': TOKEN})
    assert encendido.status_code == 200 and encendido.json()['modo_respaldo'] is True
    assert cliente.post('/predecir', json=PRODUCTO).json()['respaldo'] is True
    cliente.post('/respaldo', json={'activo': False}, headers={'X-Token-Admin': TOKEN})
    assert cliente.post('/predecir', json=PRODUCTO).json()['respaldo'] is False


def test_la_regla_es_la_media_28_mas_el_stock_de_seguridad():
    esperado = float(np.expm1(PRODUCTO['media_28_desde_16'])) + REGLA.ss_por_familia['DAIRY']
    assert regla_de(PRODUCTO) == pytest.approx(max(0.0, esperado))


def test_la_prediccion_de_respaldo_queda_registrada_como_regla(cliente):
    servicio.modo_respaldo = True
    cliente.post('/predecir', json=PRODUCTO)
    registro = leer_registro(servicio.RUTA_REGISTRO)[0]
    assert registro['modelo'] == 'regla de negocio' and registro['respaldo'] is True
