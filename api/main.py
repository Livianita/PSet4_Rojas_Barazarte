"""Servicio de predicción: pedido sugerido de perecederos por tienda–producto–día.

    uvicorn api.main:app --host 0.0.0.0 --port 8000

Endpoints
    GET  /salud            estado del servicio y si el modelo cargó
    GET  /modelo           nombre, versión, alias y run_id del modelo en uso
    POST /predecir         una fila → pedido, decisión, versión e id de la predicción
    POST /predecir/lote    varias filas (lo usa el flujo batch de Kestra)
    POST /respaldo         interruptor protegido: usar la regla de negocio en lugar del modelo
    POST /modelo/recargar  protegido: vuelve a leer el alias del registro en el acto

El modelo se carga desde models:/<nombre>@<alias> (por defecto
favorita-perecederos-modelo@champion). Cada REFRESCO_SEG segundos la API revisa a
qué versión apunta el alias; si cambió (promoción o rollback), carga la nueva sin
reconstruir la imagen ni reiniciar el contenedor.

Variables de entorno
    MLFLOW_TRACKING_URI   servidor de MLflow (en Docker: http://mlflow:5000)
    MODELO_URI            otra fuente del modelo (p. ej. una carpeta de tests/fixtures)
    MODELO_VERSION_LOCAL, MODELO_RUN_ID_LOCAL  versión y run_id que se informan con MODELO_URI local
    MODO_RESPALDO         true/false: arranca con el interruptor activado
    API_TOKEN_ADMIN       token para los endpoints protegidos (sin token quedan deshabilitados)
    RUTA_REGISTRO         SQLite con predicciones y solicitudes (por defecto /registros/api.db)
    REFRESCO_SEG          cada cuánto se revisa el alias (por defecto 30)
"""

import logging
import os
import secrets
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api.esquemas import (CONTRATO, Entrada, InfoModelo, Interruptor, Prediccion, RespuestaLote, Salud,  # noqa: E402
                          SolicitudLote)
from api.registro import Registro  # noqa: E402
from src.negocio import ReglaRespaldo, decidir  # noqa: E402

os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')   # skops con tipos confiables del proyecto
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')
os.environ.setdefault('MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR', 'false')

NOMBRE = os.environ.get('MODELO_NOMBRE', 'favorita-perecederos-modelo')
ALIAS = os.environ.get('MODELO_ALIAS', 'champion')
REFRESCO_SEG = float(os.environ.get('REFRESCO_SEG', '30'))
COLUMNAS_REALES = [c for c, r in CONTRATO['numericas'].items() if r['admite_nulo']]   # admiten nulo → float

log = logging.getLogger('api')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def _verdadero(valor):
    return str(valor).strip().lower() in ('1', 'true', 'si', 'sí', 'yes')


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Servicio:
    """Mantiene el modelo en memoria, sigue al alias del registro y aplica el interruptor."""

    def __init__(self):
        self.uri = os.environ.get('MODELO_URI') or f'models:/{NOMBRE}@{ALIAS}'
        self.por_alias = self.uri.startswith('models:/') and '@' in self.uri
        self.modelo = None
        self.info = {'nombre': NOMBRE, 'version': None, 'alias': ALIAS if self.por_alias else None,
                     'run_id': None, 'fuente': self.uri, 'cargado_en': None}
        self.error = None
        self.modo_respaldo = _verdadero(os.environ.get('MODO_RESPALDO', 'false'))
        self.motivo_interruptor = 'MODO_RESPALDO=true al iniciar' if self.modo_respaldo else None
        self.respaldo = ReglaRespaldo.cargar(Path(__file__).parent / 'respaldo.json')
        self._candado = threading.Lock()
        self._ultima_revision = 0.0

    # --- carga del modelo -------------------------------------------------
    def _version_del_alias(self):
        from mlflow.tracking import MlflowClient
        v = MlflowClient().get_model_version_by_alias(NOMBRE, ALIAS)
        return str(v.version), v.run_id

    def cargar(self):
        import mlflow
        try:
            if self.por_alias:
                version, run_id = self._version_del_alias()
                modelo = mlflow.sklearn.load_model(f'models:/{NOMBRE}/{version}')
            else:
                from mlflow.models import Model
                modelo = mlflow.sklearn.load_model(self.uri)
                version = os.environ.get('MODELO_VERSION_LOCAL', 'local')
                run_id = Model.load(self.uri).run_id or os.environ.get('MODELO_RUN_ID_LOCAL')
            self.modelo, self.error = modelo, None
            self.info.update(version=version, run_id=run_id, cargado_en=_ahora())
            log.info('modelo cargado: %s versión %s (run %s)', NOMBRE, version, run_id)
        except Exception as e:  # noqa: BLE001 — cualquier falla deja el servicio en respaldo, no caído
            self.error = f'{type(e).__name__}: {e}'[:300]
            log.warning('no se pudo cargar el modelo: %s', self.error)
        finally:
            self._ultima_revision = time.monotonic()

    def refrescar(self, forzar=False):
        """Si pasó REFRESCO_SEG, revisa el alias; recarga si cambió de versión o si no hay modelo."""
        if not forzar and time.monotonic() - self._ultima_revision < REFRESCO_SEG:
            return
        with self._candado:
            if not forzar and time.monotonic() - self._ultima_revision < REFRESCO_SEG:
                return
            if self.modelo is None or not self.por_alias:
                if self.modelo is None:
                    self.cargar()
                self._ultima_revision = time.monotonic()
                return
            try:
                version, _ = self._version_del_alias()
                if version != self.info['version']:
                    log.info('el alias %s pasó de la versión %s a la %s', ALIAS, self.info['version'], version)
                    self.cargar()
            except Exception as e:  # noqa: BLE001 — MLflow caído: se sigue con el modelo en memoria
                log.warning('no se pudo revisar el alias: %s', e)
            self._ultima_revision = time.monotonic()

    # --- predicción -------------------------------------------------------
    def predecir(self, filas):
        """Devuelve (pedidos, respaldo, motivo)."""
        X = pd.DataFrame([f.model_dump() for f in filas])
        X['DATE'] = pd.to_datetime(X['DATE'])
        X[COLUMNAS_REALES] = X[COLUMNAS_REALES].astype(float)
        motivo = None
        if self.modo_respaldo:
            motivo = f'interruptor activado ({self.motivo_interruptor or "sin motivo"})'
        elif self.modelo is None:
            motivo = f'modelo no disponible ({self.error or "sin cargar"})'
        if motivo is None:
            try:
                return np.clip(self.modelo.predict(X), 0, None), False, None
            except Exception as e:  # noqa: BLE001
                motivo = f'error al predecir ({type(e).__name__})'
                log.exception('error al predecir; se responde con la regla de negocio')
        return self.respaldo.predict(X), True, motivo


servicio = Servicio()
registro = Registro(os.environ.get('RUTA_REGISTRO', '/registros/api.db'))


@asynccontextmanager
async def ciclo_de_vida(app):
    servicio.cargar()
    yield


app = FastAPI(title='Pedido sugerido de perecederos', version='1.0', lifespan=ciclo_de_vida,
              description='Corporación Favorita: pedido diario por tienda–producto (cuantil 0,75, Co:Cu = 1:3).')


@app.middleware('http')
async def medir(request: Request, call_next):
    inicio = time.perf_counter()
    try:
        respuesta = await call_next(request)
        estado = respuesta.status_code
    except Exception:
        estado = 500
        raise
    finally:
        latencia = (time.perf_counter() - inicio) * 1000
        try:
            registro.solicitud(_ahora(), request.method, request.url.path, estado, latencia,
                               getattr(request.state, 'filas', None), getattr(request.state, 'lote', None))
        except Exception:  # noqa: BLE001 — el registro nunca tumba una respuesta
            log.exception('no se pudo registrar la solicitud')
    return respuesta


@app.exception_handler(RequestValidationError)
async def entrada_invalida(request: Request, exc: RequestValidationError):
    campos = []
    for e in exc.errors():
        campo = ''
        for p in e['loc']:
            if p == 'body':
                continue
            campo += f'[{p}]' if isinstance(p, int) else (f'.{p}' if campo else str(p))
        campos.append({'campo': campo, 'mensaje': e['msg'], 'tipo': e['type'],
                       'valor': e.get('input') if not isinstance(e.get('input'), dict) else None})
    nombres = ', '.join(dict.fromkeys(c['campo'] for c in campos))
    return JSONResponse(status_code=422, content={'error': f'entrada inválida en: {nombres}', 'campos': campos})


def admin(x_token_admin: str | None = Header(default=None)):
    esperado = os.environ.get('API_TOKEN_ADMIN')
    if not esperado:
        raise HTTPException(403, 'endpoint deshabilitado: falta API_TOKEN_ADMIN')
    if not x_token_admin or not secrets.compare_digest(x_token_admin, esperado):
        raise HTTPException(401, 'token inválido')


@app.get('/salud', response_model=Salud)
def salud():
    servicio.refrescar()
    cargado = servicio.modelo is not None
    return Salud(estado='ok' if cargado and not servicio.modo_respaldo else 'degradado', modelo_cargado=cargado,
                 modo_respaldo=servicio.modo_respaldo,
                 detalle=servicio.error if not cargado else servicio.motivo_interruptor)


@app.get('/modelo', response_model=InfoModelo)
def modelo():
    servicio.refrescar()
    return InfoModelo(**servicio.info)


def _responder(filas, lote, request):
    servicio.refrescar()
    request.state.filas, request.state.lote = len(filas), lote
    inicio = time.perf_counter()
    pedidos, respaldo, motivo = servicio.predecir(filas)
    latencia_total = (time.perf_counter() - inicio) * 1000
    latencia = latencia_total / len(filas)
    info = servicio.info if not respaldo else {**servicio.info, 'version': None, 'run_id': None, 'alias': None}
    ts = _ahora()
    salida, registros = [], []
    for fila, pedido in zip(filas, pedidos):
        p = Prediccion(id_prediccion=uuid.uuid4().hex, pedido_sugerido=round(float(pedido), 3),
                       decision=decidir(pedido), version_modelo=info['version'], alias=info['alias'],
                       run_id=info['run_id'], respaldo=respaldo, motivo_respaldo=motivo,
                       latencia_ms=round(latencia, 3))
        salida.append(p)
        registros.append({'id_prediccion': p.id_prediccion, 'ts_utc': ts, 'lote': lote,
                          'store_nbr': fila.STORE_NBR, 'item_nbr': fila.ITEM_NBR, 'fecha': str(fila.DATE),
                          'entradas': fila.model_dump(mode='json'), 'pedido_sugerido': p.pedido_sugerido,
                          'decision': p.decision, 'modelo_nombre': NOMBRE if not respaldo else 'regla de negocio',
                          'modelo_version': p.version_modelo, 'modelo_alias': p.alias, 'run_id': p.run_id,
                          'respaldo': int(respaldo), 'motivo_respaldo': motivo, 'latencia_ms': p.latencia_ms})
    registro.predicciones(registros)
    return salida, respaldo, info, latencia_total


@app.post('/predecir', response_model=Prediccion)
def predecir(entrada: Entrada, request: Request):
    salida, *_ = _responder([entrada], None, request)
    return salida[0]


@app.post('/predecir/lote', response_model=RespuestaLote)
def predecir_lote(solicitud: SolicitudLote, request: Request):
    salida, respaldo, info, latencia = _responder(solicitud.filas, solicitud.lote, request)
    return RespuestaLote(lote=solicitud.lote, n=len(salida), version_modelo=info['version'], respaldo=respaldo,
                         latencia_ms=round(latencia, 3), predicciones=salida)


@app.post('/respaldo', response_model=Salud, dependencies=[Depends(admin)])
def interruptor(cambio: Interruptor):
    servicio.modo_respaldo = cambio.activo
    servicio.motivo_interruptor = cambio.motivo if cambio.activo else None
    log.warning('interruptor de respaldo %s (%s)', 'ACTIVADO' if cambio.activo else 'desactivado', cambio.motivo)
    return salud()


@app.post('/modelo/recargar', response_model=InfoModelo, dependencies=[Depends(admin)])
def recargar():
    servicio.refrescar(forzar=True)
    return InfoModelo(**servicio.info)
