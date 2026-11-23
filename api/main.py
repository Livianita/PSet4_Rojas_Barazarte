"""Servicio de predicción del pedido de perecederos (Corporación Favorita).

Recibe un producto de una tienda para un día, con sus features (src/pipeline.py),
y responde el pedido sugerido: el cuantil 0,75 de la venta del día, que minimiza el
costo cuando un faltante cuesta 3 veces un sobrante. Se usa por lotes: el flujo de
Kestra manda cada semana todos los productos a /predecir/lote.

    uvicorn api.main:app --host 0.0.0.0 --port 8000

Rutas
    GET  /salud            estado, si el modelo cargó y qué versión sirve
    GET  /modelo           nombre, versión, alias y run_id del modelo en uso
    GET  /metricas         métricas del sistema: peticiones, errores, latencia p50 y p95
    GET  /deriva           PSI de la última semana de productos recibidos y si hay alerta
    POST /predecir         un producto → pedido, decisión, versión e id de la predicción
    POST /predecir/lote    varios productos (el lote semanal)
    POST /respaldo         interruptor protegido: usar la regla de negocio en lugar del modelo
    POST /modelo/recargar  protegido: vuelve a leer el alias del registro en el acto

El modelo se carga desde models:/<NOMBRE>@<ALIAS_MODELO> (champion). Cada
REFRESCO_SEG segundos el servicio revisa a qué versión apunta el alias; si cambió
(promoción o rollback), carga la nueva sin reconstruir la imagen.

Variables de entorno
    MLFLOW_TRACKING_URI   servidor de MLflow (en Docker: http://mlflow:5000)
    ALIAS_MODELO          alias que se sirve (por defecto champion)
    CARGAR_MODELO         si / no: las pruebas usan "no" y ponen su propio modelo
    MODELO_URI            otra fuente del modelo (p. ej. tests/fixtures/modelo en CI)
    VERSION_MODELO_LOCAL, RUN_ID_MODELO_LOCAL  versión y run_id que se informan con MODELO_URI
    MODO_RESPALDO         true: arranca con el interruptor activado
    API_TOKEN_ADMIN       token de las rutas protegidas (sin token quedan deshabilitadas)
    RUTA_REGISTRO         JSONL de predicciones (por defecto /registros/predicciones.jsonl)
    RUTA_SOLICITUDES      JSONL de peticiones, para las métricas por lote
    REFRESCO_SEG          cada cuánto se revisa el alias (por defecto 30)
"""

import json
import logging
import os
import secrets
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api.esquemas import CONTRATO, Interruptor, Lote, ProductoDia  # noqa: E402
from monitoreo.deriva import MonitorDeDeriva  # noqa: E402
from src.negocio import ReglaRespaldo, decidir  # noqa: E402

os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')   # skops, con los tipos confiables del proyecto
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')
logging.getLogger('mlflow').setLevel(logging.ERROR)
log = logging.getLogger('uvicorn.error')

NOMBRE = 'favorita-perecederos-modelo'
ALIAS = os.environ.get('ALIAS_MODELO', 'champion')
MODELO_URI = os.environ.get('MODELO_URI')
REFRESCO_SEG = float(os.environ.get('REFRESCO_SEG', '30'))
RUTA_REGISTRO = os.environ.get('RUTA_REGISTRO', '/registros/predicciones.jsonl')
RUTA_SOLICITUDES = os.environ.get('RUTA_SOLICITUDES', '/registros/solicitudes.jsonl')
CARPETA = Path(__file__).parent
COLUMNAS = list(ProductoDia.model_fields)                                       # el orden de la firma
REALES = [c for c, r in CONTRATO['numericas'].items() if r['admite_nulo']]     # admiten nulo → float

modelo = None
version_modelo = None
run_id_modelo = None
error_carga = None
ultima_revision = 0.0
modo_respaldo = os.environ.get('MODO_RESPALDO', 'false').lower() in ('1', 'true', 'si')
motivo_interruptor = 'MODO_RESPALDO=true al arrancar' if modo_respaldo else None
respaldo = ReglaRespaldo.cargar(CARPETA / 'respaldo.json')
with open(CARPETA / 'referencia_deriva.json', encoding='utf-8') as archivo:
    monitor = MonitorDeDeriva(json.load(archivo))


def cargar_modelo():
    """Carga la versión con el alias ALIAS (o MODELO_URI). Si falla, el servicio
    sigue en pie y responde con la regla de negocio."""
    global modelo, version_modelo, run_id_modelo, error_carga, ultima_revision
    import mlflow.sklearn
    from mlflow import MlflowClient
    try:
        if MODELO_URI:
            from mlflow.models import Model
            modelo = mlflow.sklearn.load_model(MODELO_URI)
            version_modelo = os.environ.get('VERSION_MODELO_LOCAL', 'local')
            run_id_modelo = Model.load(MODELO_URI).run_id or os.environ.get('RUN_ID_MODELO_LOCAL')
        else:
            version = MlflowClient().get_model_version_by_alias(NOMBRE, ALIAS)
            modelo = mlflow.sklearn.load_model(f'models:/{NOMBRE}/{version.version}')
            version_modelo, run_id_modelo = version.version, version.run_id
        error_carga = None
        log.info('modelo cargado: %s versión %s (run %s)', NOMBRE, version_modelo, run_id_modelo)
    except Exception as e:  # noqa: BLE001 — cualquier falla deja el servicio en respaldo, no caído
        error_carga = f'{type(e).__name__}: {e}'[:300]
        log.warning('no se pudo cargar el modelo: %s', error_carga)
    ultima_revision = time.monotonic()


def revisar_alias(forzar=False):
    """Cada REFRESCO_SEG segundos: si el alias apunta a otra versión, o si no hay
    modelo, vuelve a cargar. Así una promoción o un rollback llegan sin reconstruir."""
    global ultima_revision
    if os.environ.get('CARGAR_MODELO', 'si') != 'si':
        return
    if not forzar and time.monotonic() - ultima_revision < REFRESCO_SEG:
        return
    ultima_revision = time.monotonic()
    if modelo is None or MODELO_URI:
        if modelo is None or forzar:
            cargar_modelo()
        return
    from mlflow import MlflowClient
    try:
        actual = MlflowClient().get_model_version_by_alias(NOMBRE, ALIAS).version
        if actual != version_modelo:
            log.info('el alias %s pasó de la versión %s a la %s', ALIAS, version_modelo, actual)
            cargar_modelo()
    except Exception as e:  # noqa: BLE001 — MLflow caído: se sigue con el modelo en memoria
        log.warning('no se pudo revisar el alias: %s', e)


# MLflow se usa solo si hay que cargar el modelo: las pruebas no lo necesitan,
# y en GitHub Actions no hay servidor de MLflow.
if os.environ.get('CARGAR_MODELO', 'si') == 'si':
    cargar_modelo()


class Metricas:
    """Las métricas del sistema, en memoria: una latencia y un código por cada
    petición a /predecir o /predecir/lote. Cada petición queda además en
    RUTA_SOLICITUDES, para calcularlas por lote en el monitoreo."""

    def __init__(self):
        self.latencias_ms = []
        self.codigos = []
        self.productos = 0

    def registrar(self, latencia_ms, codigo, productos=0):
        self.latencias_ms.append(latencia_ms)
        self.codigos.append(codigo)
        self.productos += productos or 0

    def resumen(self):
        if not self.latencias_ms:
            p50 = p95 = None
        else:
            p50 = round(float(np.percentile(self.latencias_ms, 50)), 2)
            p95 = round(float(np.percentile(self.latencias_ms, 95)), 2)
        return {
            'peticiones': len(self.codigos),
            'productos': self.productos,
            'errores_validacion': sum(1 for codigo in self.codigos if codigo == 422),
            'errores_cliente': sum(1 for codigo in self.codigos if 400 <= codigo < 500),
            'errores_servidor': sum(1 for codigo in self.codigos if codigo >= 500),
            'latencia_p50_ms': p50,
            'latencia_p95_ms': p95,
        }


metricas = Metricas()
app = FastAPI(title='Pedido sugerido de perecederos',
              description='Pedido diario por tienda–producto (cuantil 0,75, Co:Cu = 1:3).')


@app.middleware('http')
async def medir(request: Request, call_next):
    """Corre alrededor de cada petición: lo que está antes de call_next pasa antes
    de la ruta, y lo que está después, cuando ya hay respuesta."""
    if not request.url.path.startswith('/predecir'):
        return await call_next(request)
    inicio = time.perf_counter()
    try:
        respuesta = await call_next(request)
        codigo = respuesta.status_code
    except Exception:
        codigo = 500
        raise
    finally:
        latencia_ms = (time.perf_counter() - inicio) * 1000
        productos = getattr(request.state, 'productos', 0)
        metricas.registrar(latencia_ms, codigo, productos)
        with open(RUTA_SOLICITUDES, 'a', encoding='utf-8') as archivo:
            archivo.write(json.dumps({'momento': datetime.now().isoformat(), 'ruta': request.url.path,
                                      'codigo': codigo, 'latencia_ms': round(latencia_ms, 3),
                                      'productos': productos, 'lote': getattr(request.state, 'lote', None)}) + '\n')
    return respuesta


@app.exception_handler(RequestValidationError)
async def entrada_invalida(request: Request, exc: RequestValidationError):
    """422 con el campo que falló: 'FAMILY', o 'filas[3].FAMILY' dentro de un lote."""
    campos = []
    for error in exc.errors():
        campo = ''
        for parte in error['loc']:
            if parte != 'body':
                campo += f'[{parte}]' if isinstance(parte, int) else (f'.{parte}' if campo else str(parte))
        valor = error.get('input')
        campos.append({'campo': campo, 'mensaje': error['msg'], 'tipo': error['type'],
                       'valor': None if isinstance(valor, dict) else valor})
    nombres = ', '.join(dict.fromkeys(c['campo'] for c in campos))
    # La ruta no llegó a correr: el lote se toma del cuerpo para que el 422 quede atribuido a
    # su lote en RUTA_SOLICITUDES (el middleware lee request.state después de responder).
    if isinstance(exc.body, dict):
        request.state.lote = exc.body.get('lote') if isinstance(exc.body.get('lote'), str) else None
    return JSONResponse(status_code=422, content={'error': f'entrada inválida en: {nombres}', 'campos': campos})


def solo_administrador(x_token_admin: str | None = Header(default=None)):
    esperado = os.environ.get('API_TOKEN_ADMIN')
    if not esperado:
        raise HTTPException(403, 'ruta deshabilitada: falta API_TOKEN_ADMIN')
    if not x_token_admin or not secrets.compare_digest(x_token_admin, esperado):
        raise HTTPException(401, 'token inválido')


@app.get('/salud')
def salud():
    revisar_alias()
    return {'estado': 'ok' if modelo is not None and not modo_respaldo else 'degradado',
            'modelo_cargado': modelo is not None, 'version_modelo': version_modelo,
            'modo_respaldo': modo_respaldo, 'detalle': motivo_interruptor if modo_respaldo else error_carga}


@app.get('/modelo')
def ver_modelo():
    revisar_alias()
    return {'nombre': NOMBRE, 'version': version_modelo, 'alias': None if MODELO_URI else ALIAS,
            'run_id': run_id_modelo, 'fuente': MODELO_URI or f'models:/{NOMBRE}@{ALIAS}'}


@app.get('/metricas')
def ver_metricas():
    return metricas.resumen()


@app.get('/deriva')
def ver_deriva():
    return monitor.estado()


def pedir(productos):
    """Pedido sugerido de cada producto, y si respondió el respaldo y por qué."""
    datos = pd.DataFrame([producto.model_dump() for producto in productos])[COLUMNAS]
    datos['DATE'] = pd.to_datetime(datos['DATE'])
    datos[REALES] = datos[REALES].astype(float)
    if modo_respaldo:
        return respaldo.predict(datos), f'interruptor activado ({motivo_interruptor or "sin motivo"})'
    if modelo is None:
        return respaldo.predict(datos), f'modelo no disponible ({error_carga or "sin cargar"})'
    try:
        return np.clip(modelo.predict(datos), 0, None), None
    except Exception as e:  # noqa: BLE001
        log.exception('error al predecir; responde la regla de negocio')
        return respaldo.predict(datos), f'error al predecir ({type(e).__name__})'


def predecir_y_registrar(productos, lote, request):
    revisar_alias()
    request.state.productos, request.state.lote = len(productos), lote
    inicio = time.perf_counter()
    pedidos, motivo = pedir(productos)
    latencia_ms = round((time.perf_counter() - inicio) * 1000 / len(productos), 3)
    usa_respaldo = motivo is not None
    version = None if usa_respaldo else version_modelo
    run_id = None if usa_respaldo else run_id_modelo
    momento = datetime.now().isoformat()
    respuestas = []
    with open(RUTA_REGISTRO, 'a', encoding='utf-8') as archivo:
        for producto, pedido in zip(productos, pedidos):
            respuesta = {'id_prediccion': uuid.uuid4().hex, 'pedido_sugerido': round(float(pedido), 3),
                         'decision': decidir(pedido), 'version_modelo': version, 'run_id': run_id,
                         'respaldo': usa_respaldo, 'motivo_respaldo': motivo, 'latencia_ms': latencia_ms}
            registro = {'id_prediccion': respuesta['id_prediccion'], 'momento': momento, 'lote': lote,
                        'modelo': NOMBRE if not usa_respaldo else 'regla de negocio', 'alias': ALIAS}
            registro.update(respuesta)
            registro['entrada'] = producto.model_dump(mode='json')
            archivo.write(json.dumps(registro) + '\n')
            monitor.registrar(producto.model_dump())
            respuestas.append(respuesta)
    return respuestas


@app.post('/predecir')
def predecir(producto: ProductoDia, request: Request):
    return predecir_y_registrar([producto], None, request)[0]


@app.post('/predecir/lote')
def predecir_lote(lote: Lote, request: Request):
    respuestas = predecir_y_registrar(lote.filas, lote.lote, request)
    return {'lote': lote.lote, 'n': len(respuestas), 'version_modelo': respuestas[0]['version_modelo'],
            'respaldo': respuestas[0]['respaldo'], 'predicciones': respuestas}


@app.post('/respaldo', dependencies=[Depends(solo_administrador)])
def interruptor(cambio: Interruptor):
    global modo_respaldo, motivo_interruptor
    modo_respaldo = cambio.activo
    motivo_interruptor = cambio.motivo if cambio.activo else None
    log.warning('interruptor de respaldo %s (%s)', 'ACTIVADO' if cambio.activo else 'desactivado', cambio.motivo)
    return salud()


@app.post('/modelo/recargar', dependencies=[Depends(solo_administrador)])
def recargar():
    revisar_alias(forzar=True)
    return ver_modelo()
