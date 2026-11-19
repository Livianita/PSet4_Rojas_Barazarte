"""Esquema de entrada de la API.

La entrada coincide con la firma del modelo registrado en MLflow (31 columnas:
13 + 2 numéricas, 8 indicadores 0/1, 5 categóricas y la clave tienda–producto–fecha).
Rangos y categorías permitidas vienen de api/contrato.json, que genera
src/reentrenar.py a partir del entrenamiento y también queda como artefacto de la
corrida en MLflow. Un campo que no cumple devuelve 422 con el nombre del campo.

Las features de ventas están en escala log1p y miran 16 días o más hacia atrás
(regla de no fuga del PSet 3). Un valor nulo en una numérica significa "faltante"
(series jóvenes sin historia suficiente): el imputador del modelo lo resuelve.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CONTRATO = json.loads((Path(__file__).parent / 'contrato.json').read_text(encoding='utf-8'))
_NUM = CONTRATO['numericas']
_CAT = CONTRATO['categoricas']


def _real(campo, descripcion):
    r = _NUM[campo]
    tipo = Annotated[float, Field(ge=r['min'], le=r['max'], description=descripcion)]
    return Optional[tipo] if r['admite_nulo'] else tipo


def _entero(campo, descripcion):
    r = _NUM[campo]
    return Annotated[int, Field(ge=r['min'], le=r['max'], description=descripcion)]


Indicador = Annotated[Literal[0, 1], Field(description='indicador 0/1 del calendario')]
DiaSemana = Literal[tuple(_CAT['DAY_OF_WEEK_ISO'])]
Familia = Literal[tuple(_CAT['FAMILY'])]
ClaseItem = Literal[tuple(_CAT['ITEM_CLASS'])]
TipoTienda = Literal[tuple(_CAT['STORE_TYPE'])]
ClusterTienda = Literal[tuple(_CAT['STORE_CLUSTER'])]
TIENDA_MIN, TIENDA_MAX = CONTRATO['identificadores']['STORE_NBR']


class ProductoDia(BaseModel):
    """Lo que se sabe de un producto en una tienda, para un día, 16 días antes:
    las features que calcula construir_features de src/pipeline.py."""

    model_config = ConfigDict(extra='forbid', json_schema_extra={'example': {
        'venta_lag_16': 1.79, 'venta_lag_21': 2.08, 'venta_lag_28': 1.61, 'venta_lag_35': 1.95,
        'venta_lag_42': 2.2, 'media_mismo_dia_4': 1.96, 'media_7_desde_16': 1.85, 'media_28_desde_16': 1.88,
        'std_28_desde_16': 0.41, 'frac_ceros_28_desde_16': 0.0, 'dias_sin_venta_16': 0,
        'nivel_serie_16': 1.9, 'transacciones_lag_16': 7.4, 'DAY_OF_MONTH': 12, 'APPLICABLE_EVENT_COUNT': 0,
        'IS_PAYDAY_PROXY': 0, 'IS_MONTH_END': 0, 'IS_HOLIDAY': 0, 'IS_TRANSFER_DAY': 0,
        'IS_ADDITIONAL_DAY': 0, 'IS_BRIDGE_DAY': 0, 'IS_WORK_DAY': 1, 'HAS_SPECIAL_EVENT': 0,
        'DAY_OF_WEEK_ISO': '1', 'FAMILY': 'DAIRY', 'ITEM_CLASS': '2112', 'STORE_TYPE': 'D',
        'STORE_CLUSTER': '13', 'STORE_NBR': 44, 'ITEM_NBR': 1473474, 'DATE': '2017-06-12'}})

    venta_lag_16: _real('venta_lag_16', 'log1p de la venta en t−16')
    venta_lag_21: _real('venta_lag_21', 'log1p de la venta en t−21')
    venta_lag_28: _real('venta_lag_28', 'log1p de la venta en t−28')
    venta_lag_35: _real('venta_lag_35', 'log1p de la venta en t−35')
    venta_lag_42: _real('venta_lag_42', 'log1p de la venta en t−42')
    media_mismo_dia_4: _real('media_mismo_dia_4', 'media de los rezagos 21, 28, 35 y 42')
    media_7_desde_16: _real('media_7_desde_16', 'media de [t−22, t−16]')
    media_28_desde_16: _real('media_28_desde_16', 'media de [t−43, t−16]')
    std_28_desde_16: _real('std_28_desde_16', 'desviación de [t−43, t−16]')
    frac_ceros_28_desde_16: _real('frac_ceros_28_desde_16', 'fracción de días sin venta en [t−43, t−16]')
    dias_sin_venta_16: _real('dias_sin_venta_16', 'días desde la última venta, vistos en t−16 (tope 90)')
    nivel_serie_16: _real('nivel_serie_16', 'media histórica de la serie hasta t−16')
    transacciones_lag_16: _real('transacciones_lag_16', 'log1p de las transacciones de la tienda en t−16')
    DAY_OF_MONTH: _entero('DAY_OF_MONTH', 'día del mes')
    APPLICABLE_EVENT_COUNT: _entero('APPLICABLE_EVENT_COUNT', 'eventos de calendario que aplican a la tienda')
    IS_PAYDAY_PROXY: Indicador
    IS_MONTH_END: Indicador
    IS_HOLIDAY: Indicador
    IS_TRANSFER_DAY: Indicador
    IS_ADDITIONAL_DAY: Indicador
    IS_BRIDGE_DAY: Indicador
    IS_WORK_DAY: Indicador
    HAS_SPECIAL_EVENT: Indicador
    DAY_OF_WEEK_ISO: DiaSemana
    FAMILY: Familia
    ITEM_CLASS: ClaseItem
    STORE_TYPE: TipoTienda
    STORE_CLUSTER: ClusterTienda
    STORE_NBR: Annotated[int, Field(ge=TIENDA_MIN, le=TIENDA_MAX)]
    ITEM_NBR: Annotated[int, Field(gt=0)]
    DATE: dt.date


class Lote(BaseModel):
    """Los productos de un lote semanal, con el identificador del lote."""
    model_config = ConfigDict(extra='forbid')
    lote: Optional[str] = Field(None, max_length=64, description='identificador del lote (semana)')
    filas: list[ProductoDia] = Field(min_length=1, max_length=50_000)


class Interruptor(BaseModel):
    """Encender o apagar el modo de respaldo (regla de negocio en lugar del modelo)."""
    activo: bool
    motivo: Optional[str] = Field(None, max_length=200)
