"""Deriva de datos: el PSI de cada feature vigilada contra su distribución de entrenamiento.

    from monitoreo.deriva import MonitorDeDeriva, psi, referencia_deriva

La referencia (api/referencia_deriva.json) guarda, por feature, las casillas y las
proporciones de entrenamiento: los deciles para una numérica y cada categoría para
una categórica. La usan el servicio (ruta /deriva, con los últimos `ventana`
productos que recibió) y el flujo de monitoreo de Kestra (cada lote completo).

La alerta se decide con el PSI. Las pruebas de Kolmogorov-Smirnov (numéricas) y de
chi-cuadrado (categóricas) son el respaldo: comparan el lote con una muestra de
entrenamiento (monitoreo/referencia_muestra.parquet). Con 14.000 filas por lote rechazan
la igualdad incluso en semanas normales (p-valores de 1e-7 a 1e-21 en los lotes 1 y 3),
por eso no deciden la alerta: confirman la dirección de un PSI alto y dan un estadístico
que no depende de las casillas.

calidad_datos cuenta, contra el contrato de la API (api/contrato.json), los faltantes por
feature, los valores fuera de rango y las categorías no vistas en el entrenamiento.
"""

from pathlib import Path

import numpy as np
import pandas as pd

MINIMO = 0.0001
UMBRAL_PSI = 0.20             # en los lotes sin alterar el PSI máximo es ≤ 0,043
UMBRAL_PSI_MODERADO = 0.10
RUTA_MUESTRA_REFERENCIA = Path(__file__).parent / 'referencia_muestra.parquet'

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

    def __init__(self, referencia, ventana=14_000, umbral=UMBRAL_PSI):
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


def muestra_referencia(X, n=20_000, semilla=0, numericas=NUMERICAS_VIGILADAS, categoricas=CATEGORICAS_VIGILADAS):
    """Muestra de entrenamiento de las features vigiladas, para las pruebas estadísticas."""
    muestra = X[numericas + categoricas].sample(min(n, len(X)), random_state=semilla).reset_index(drop=True)
    muestra[categoricas] = muestra[categoricas].astype(str)
    return muestra


def pruebas_estadisticas(muestra, datos, numericas=NUMERICAS_VIGILADAS, categoricas=CATEGORICAS_VIGILADAS):
    """KS de dos muestras para cada numérica y chi-cuadrado de homogeneidad (tabla 2 × categorías,
    con las categorías nuevas incluidas) para cada categórica, contra `muestra`."""
    from scipy.stats import chi2_contingency, ks_2samp

    datos = pd.DataFrame(datos)
    resultado = {}
    for columna in numericas:
        referencia = pd.to_numeric(muestra[columna], errors='coerce').dropna()
        actual = pd.to_numeric(datos[columna], errors='coerce').dropna()
        prueba = ks_2samp(referencia, actual)
        resultado[columna] = {'prueba': 'ks', 'estadistico': round(float(prueba.statistic), 4),
                              'p_valor': float(prueba.pvalue)}
    for columna in categoricas:
        tabla = pd.concat([muestra[columna].astype(str).value_counts().rename('referencia'),
                           datos[columna].astype(str).value_counts().rename('lote')], axis=1).fillna(0)
        estadistico, p_valor, _, _ = chi2_contingency(tabla.T.to_numpy())
        resultado[columna] = {'prueba': 'chi2', 'estadistico': round(float(estadistico), 4),
                              'p_valor': float(p_valor)}
    return resultado


def calidad_datos(contrato, datos):
    """Faltantes por feature (proporción), valores fuera de rango y categorías no vistas,
    contra el contrato de entrada de la API."""
    datos = pd.DataFrame(datos)
    columnas = list(contrato['numericas']) + contrato['ya_listas'] + list(contrato['categoricas'])
    faltantes = {c: round(float(datos[c].isna().mean()), 6) for c in columnas}
    fuera_de_rango = {}
    for c, rango in contrato['numericas'].items():
        valores = pd.to_numeric(datos[c], errors='coerce')
        fuera_de_rango[c] = int(((valores < rango['min']) | (valores > rango['max'])).sum())
    for c in contrato['ya_listas']:
        fuera_de_rango[c] = int((datos[c].notna() & ~datos[c].isin([0, 1])).sum())
    no_vistas = {c: int((datos[c].notna() & ~datos[c].astype(str).isin(permitidas)).sum())
                 for c, permitidas in contrato['categoricas'].items()}
    # Faltantes que el contrato no admite (las numéricas de historia sí admiten nulo: series jóvenes).
    obligatorias = ([c for c, r in contrato['numericas'].items() if not r['admite_nulo']]
                    + contrato['ya_listas'] + list(contrato['categoricas']))
    return {'filas': len(datos), 'faltantes': faltantes, 'fuera_de_rango': fuera_de_rango,
            'categorias_no_vistas': no_vistas, 'faltantes_max': max(faltantes.values()),
            'faltantes_obligatorios': int(datos[obligatorias].isna().sum().sum()),
            'fuera_de_rango_total': sum(fuera_de_rango.values()),
            'categorias_no_vistas_total': sum(no_vistas.values())}
