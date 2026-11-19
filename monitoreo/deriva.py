"""Deriva de datos: el PSI de cada feature vigilada contra su distribución de entrenamiento.

    from monitoreo.deriva import MonitorDeDeriva, psi, referencia_deriva

La referencia (api/referencia_deriva.json) guarda, por feature, las casillas y las
proporciones de entrenamiento: los deciles para una numérica y cada categoría para
una categórica. La usan el servicio (ruta /deriva, con los últimos `ventana`
productos que recibió) y el flujo de monitoreo de Kestra (cada lote completo).
"""

import numpy as np
import pandas as pd

MINIMO = 0.0001

# Features vigiladas: las de mayor importancia por permutación del modelo de producción
# (nivel_serie_16 y media_mismo_dia_4 mandan), la actividad de la tienda y la mezcla de
# lo que llega (familia, tipo de tienda y día de la semana).
NUMERICAS_VIGILADAS = ['nivel_serie_16', 'media_mismo_dia_4', 'media_7_desde_16', 'media_28_desde_16',
                       'venta_lag_16', 'frac_ceros_28_desde_16', 'transacciones_lag_16']
CATEGORICAS_VIGILADAS = ['FAMILY', 'STORE_TYPE', 'DAY_OF_WEEK_ISO']


def proporciones_numericas(valores, cortes):
    """Proporción de los valores en cada casilla. `cortes` son los límites
    interiores: con 9 cortes hay 10 casillas, la primera hasta el primer corte y
    la última desde el último, abiertas. Los nulos no cuentan."""
    valores = pd.to_numeric(pd.Series(valores, dtype='object'), errors='coerce').dropna().to_numpy(dtype=float)
    if len(valores) == 0:
        return np.zeros(len(cortes) + 1)
    conteo, _ = np.histogram(valores, bins=[-np.inf] + list(cortes) + [np.inf])
    return conteo / conteo.sum()


def proporciones_categoricas(valores, categorias):
    """Proporción de los valores en cada categoría, en el orden de `categorias`.
    Un valor que no está en `categorias` no cuenta en ninguna casilla, pero sí en el total."""
    valores = pd.Series(valores, dtype='object').astype(str)
    if len(valores) == 0:
        return np.zeros(len(categorias))
    return valores.value_counts().reindex(categorias, fill_value=0).to_numpy() / len(valores)


def psi(referencia, actual):
    """PSI = Σ (a − r) · ln(a / r), con MINIMO en las casillas vacías."""
    r = np.clip(np.asarray(referencia, dtype=float), MINIMO, None)
    a = np.clip(np.asarray(actual, dtype=float), MINIMO, None)
    return float(np.sum((a - r) * np.log(a / r)))


def referencia_deriva(X, numericas=NUMERICAS_VIGILADAS, categoricas=CATEGORICAS_VIGILADAS):
    """Casillas y proporciones de entrenamiento de cada feature vigilada.
    Los deciles se calculan sobre valores únicos de corte: features con muchos
    ceros (frac_ceros, venta_lag) quedan con menos de 10 casillas."""
    referencia = {}
    for columna in numericas:
        valores = X[columna].dropna()
        cortes = sorted(set(np.round(np.quantile(valores, np.linspace(0, 1, 11))[1:-1], 6)))
        referencia[columna] = {'tipo': 'numerica', 'cortes': [float(c) for c in cortes],
                               'proporciones': [float(p) for p in proporciones_numericas(valores, cortes)],
                               'minimo': float(valores.min()), 'maximo': float(valores.max()),
                               'faltantes': float(X[columna].isna().mean())}
    for columna in categoricas:
        categorias = sorted(X[columna].astype(str).unique(), key=lambda v: (len(v), v))
        referencia[columna] = {'tipo': 'categorica', 'categorias': categorias,
                               'proporciones': [float(p) for p in proporciones_categoricas(X[columna], categorias)]}
    return referencia


def psi_por_feature(referencia, datos):
    """El PSI de cada feature de la referencia en `datos` (un DataFrame o lista de dicts)."""
    datos = pd.DataFrame(datos)
    resultado = {}
    for columna, ref in referencia.items():
        if ref['tipo'] == 'numerica':
            actual = proporciones_numericas(datos[columna], ref['cortes'])
        else:
            actual = proporciones_categoricas(datos[columna], ref['categorias'])
        resultado[columna] = round(psi(ref['proporciones'], actual), 4)
    return resultado


class MonitorDeDeriva:
    """Guarda los últimos `ventana` productos que recibió el servicio y compara su
    distribución con la de entrenamiento. Una ventana es una semana de pedidos:
    2.000 tienda–producto × 7 días = 14.000 filas."""

    def __init__(self, referencia, ventana=14_000, umbral=0.25):
        self.referencia = referencia
        self.ventana = ventana
        self.umbral = umbral
        self.filas = []

    def registrar(self, fila):
        """Agrega un producto (un diccionario con las features vigiladas) y deja solo los últimos `ventana`."""
        self.filas.append({columna: fila.get(columna) for columna in self.referencia})
        if len(self.filas) > self.ventana:
            del self.filas[:len(self.filas) - self.ventana]

    def estado(self):
        """'filas_en_ventana', 'psi' por feature y 'alerta': True solo si la ventana
        está llena y algún PSI pasa el umbral."""
        if not self.filas:
            return {'filas_en_ventana': 0, 'umbral': self.umbral, 'psi': {}, 'alerta': False}
        valores = psi_por_feature(self.referencia, self.filas)
        llena = len(self.filas) >= self.ventana
        return {'filas_en_ventana': len(self.filas), 'umbral': self.umbral, 'psi': valores,
                'alerta': bool(llena and max(valores.values()) > self.umbral)}
