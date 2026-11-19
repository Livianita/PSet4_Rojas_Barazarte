"""Métrica de negocio, decisión y regla de respaldo (una sola definición para todo el proyecto).

    from src.negocio import resultado_negocio, decidir, ReglaRespaldo

La decisión del negocio es el pedido diario de cada tienda–producto perecedero.
El modelo de producción (GB-cuantil 0,75) entrega directamente el pedido: el
cuantil q = Cu / (Cu + Co) = 3 / (3 + 1) = 0,75 minimiza el costo esperado
cuando un faltante cuesta 3 veces un sobrante (escenario principal 1:3).

La regla de respaldo es la línea base de negocio del PSet 3 (media de 28 días +
stock de seguridad aditivo por familia), escrita para que se pueda calcular
solo con la fila que llega a la API: usa la feature media_28_desde_16, que es la
media de log1p(ventas) en [t−43, t−16]. No depende de MLflow ni del modelo, por
eso sirve cuando el modelo no carga o cuando se activa el interruptor.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

CO, CU = 1, 3                      # costo de un sobrante y de un faltante (escenario principal 1:3)
CUANTIL = CU / (CU + CO)           # 0,75
ESCENARIOS = {'3:1': (3, 1), '1:1': (1, 1), '1:3': (1, 3)}


def resultado_negocio(y, pedido, co=CO, cu=CU):
    """Merma, cobertura y costo ponderado de un conjunto de pedidos (misma fórmula del PSet 3)."""
    y, pedido = np.asarray(y, dtype=float), np.asarray(pedido, dtype=float)
    sobrantes, faltantes = np.maximum(pedido - y, 0).sum(), np.maximum(y - pedido, 0).sum()
    # Si no se pide nada no hay merma posible: se reporta 0 en lugar de 0/0.
    return {'merma': sobrantes / pedido.sum() if pedido.sum() > 0 else 0.0,
            'cobertura': 1 - faltantes / y.sum() if y.sum() > 0 else 1.0,
            'sobrantes': sobrantes, 'faltantes': faltantes, 'costo': co * sobrantes + cu * faltantes}


def decidir(pedido):
    """Acción del negocio a partir del pedido sugerido (unidades)."""
    pedido = float(pedido)
    return 'reponer' if pedido >= 0.5 else 'no reponer'


class ReglaRespaldo:
    """Línea base de negocio: expm1(media_28_desde_16) + SS aditivo por familia.

    El SS de cada familia es el cuantil 0,75 de los errores (real − media 28) en el
    entrenamiento; se guarda en un JSON pequeño versionado en el repositorio.
    """

    def __init__(self, ss_por_familia=None, cuantil=CUANTIL):
        self.ss_por_familia = dict(ss_por_familia or {})
        self.cuantil = cuantil

    @staticmethod
    def media_28(X):
        m = pd.to_numeric(pd.Series(np.asarray(X['media_28_desde_16'], dtype=float)), errors='coerce')
        return np.expm1(m.fillna(0).clip(lower=0)).to_numpy()

    def fit(self, X, y):
        errores = pd.Series(np.asarray(y, dtype=float) - self.media_28(X))
        self.ss_por_familia = errores.groupby(np.asarray(X['FAMILY'])).quantile(self.cuantil).round(4).to_dict()
        return self

    def predict(self, X):
        ss = pd.Series(np.asarray(X['FAMILY'])).map(self.ss_por_familia).fillna(0).to_numpy()
        return np.maximum(0, self.media_28(X) + ss)

    def guardar(self, ruta):
        Path(ruta).write_text(json.dumps({'regla': 'media_28_desde_16 + SS aditivo por familia',
                                          'cuantil': self.cuantil, 'ss_por_familia': self.ss_por_familia},
                                         indent=2, ensure_ascii=False), encoding='utf-8')

    @classmethod
    def cargar(cls, ruta):
        d = json.loads(Path(ruta).read_text(encoding='utf-8'))
        return cls(d['ss_por_familia'], d.get('cuantil', CUANTIL))
