"""Features, preparación y división temporal del PSet 3.

    from src.pipeline import construir_features, dividir, preparacion, pliegues

Los notebooks importan estas funciones en vez de copiarlas, así todos los
experimentos usan exactamente las mismas features y la misma preparación.

Regla de no fuga: el modelo pronostica cada uno de los 16 días posteriores a un
corte. Toda feature derivada de ventas o transacciones usa solo datos de
t−16 o antes, de modo que existe para cualquier día del horizonte. Lo único
del propio día t es lo que se conoce de antemano: calendario, feriados y
promociones planificadas.
"""

import warnings

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import make_scorer
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

OBJETIVO = 'UNIT_SALES_TARGET'
SERIE = ['STORE_NBR', 'ITEM_NBR']
CLAVE = SERIE + ['DATE']

HORIZONTE = 16
REZAGOS = (16, 21, 28, 35, 42)        # 21, 28, 35 y 42: mismo día de la semana que t
INICIO_MODELADO = '2016-09-13'        # primer día con la ventana [t−43, t−16] completa
INICIO_PRUEBA = '2017-07-31'          # prueba = últimos 16 días de la OBT (se usa una vez)
FIN_PRUEBA = '2017-08-15'

# Derivadas de la historia (todas con datos de t−16 o antes). Ventas en escala log1p.
DERIVADAS = [f'venta_lag_{k}' for k in REZAGOS] + [
    'media_mismo_dia_4',        # media de los rezagos 21, 28, 35 y 42
    'media_7_desde_16',         # media de [t−22, t−16]
    'media_28_desde_16',        # media de [t−43, t−16]
    'std_28_desde_16',
    'frac_ceros_28_desde_16',   # intermitencia (hallazgo 3 del EDA)
    'dias_sin_venta_16',        # días desde la última venta, vistos en t−16
    'nivel_serie_16',           # media histórica de la serie hasta t−16 (hallazgo 4)
    'transacciones_lag_16',     # log1p de transacciones de la tienda en t−16 (hallazgo 5)
]
NUMERICAS = DERIVADAS + ['DAY_OF_MONTH', 'APPLICABLE_EVENT_COUNT']
YA_LISTAS = ['IS_PAYDAY_PROXY', 'IS_MONTH_END', 'IS_HOLIDAY', 'IS_TRANSFER_DAY',
             'IS_ADDITIONAL_DAY', 'IS_BRIDGE_DAY', 'IS_WORK_DAY', 'HAS_SPECIAL_EVENT']
CATEGORICAS = ['DAY_OF_WEEK_ISO', 'FAMILY', 'ITEM_CLASS', 'STORE_TYPE', 'STORE_CLUSTER']
PROMOCION = ['ONPROMOTION']           # fuera por defecto: ver la ablación del notebook 02

# Columnas de la OBT que no entran al modelo y por qué.
EXCLUIDAS = {
    'UNIT_SALES_ORIGINAL': 'es el objetivo sin recortar',
    'IS_RETURN': 'se deriva del objetivo del mismo día',
    'IS_OBSERVED': 'auditoría del PSet 2: revela si hubo venta',
    'IS_IMPUTED_ZERO': 'auditoría del PSet 2: revela y = 0',
    'IS_ONPROMOTION_IMPUTED': 'auditoría del PSet 2: revela y = 0',
    'IS_AFTER_LAST_SALE': 'auditoría del PSet 2: usa el futuro de la serie',
    'TRANSACTIONS_OBSERVED': 'mismo día: no existe al predecir (se usa rezagada 16)',
    'IS_TRANSACTIONS_MISSING': 'mismo día: no existe al predecir',
    'OIL_PRICE_PREPARED': 'mismo día y sin relación con el objetivo (EDA §5)',
    'STORE_NBR': 'identificador: el nivel de la serie lo resume sin memorizar',
    'ITEM_NBR': 'identificador: el nivel de la serie lo resume sin memorizar',
    'YEAR': 'un solo año de historia: confunde tendencia con estacionalidad',
    'MONTH': 'un solo año de historia: agosto aparece una sola vez antes de la prueba',
    'IS_WEEKEND': 'redundante con DAY_OF_WEEK_ISO',
    'CITY': 'redundante con STORE_CLUSTER y STORE_TYPE para 54 tiendas',
    'STATE': 'redundante con STORE_CLUSTER y STORE_TYPE para 54 tiendas',
}


def _ancho(datos, columna, fechas):
    """Serie × fecha, con todas las fechas del calendario (los huecos quedan NaN),
    para que un rezago de k días sea siempre k días de calendario."""
    return (datos.pivot(index=SERIE, columns='DATE', values=columna)
            .reindex(columns=fechas))


def _rodar(ancho, ventana, funcion):
    rodante = ancho.T.rolling(ventana, min_periods=ventana // 2)
    return getattr(rodante, funcion)().T


def construir_features(ventas):
    """Agrega las features derivadas a la muestra de la OBT.

    Devuelve una fila por tienda–producto–día desde INICIO_MODELADO, con las
    columnas originales (para el objetivo y los análisis) más DERIVADAS.
    Las booleanas pasan a 0/1 y las categóricas a texto.
    """
    d = ventas.sort_values(CLAVE).reset_index(drop=True)
    fechas = pd.date_range(d['DATE'].min(), d['DATE'].max(), freq='D', name='DATE')
    fechas = fechas.astype(d['DATE'].dtype)

    venta = np.log1p(_ancho(d, OBJETIVO, fechas).clip(lower=0))
    transacciones = np.log1p(_ancho(d, 'TRANSACTIONS_OBSERVED', fechas))
    ceros = (venta == 0).astype(float).where(venta.notna())

    posicion = np.arange(len(fechas), dtype=float)
    ultima = pd.DataFrame(np.where(venta.to_numpy() > 0, posicion, np.nan),
                          index=venta.index, columns=fechas).ffill(axis=1)
    dias_sin_venta = pd.DataFrame(np.minimum(posicion - ultima.to_numpy(), 90),
                                  index=venta.index, columns=fechas)

    f = {f'venta_lag_{k}': venta.shift(k, axis=1) for k in REZAGOS}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)  # series sin ningún rezago aún
        mismo_dia = np.nanmean(np.stack([f[f'venta_lag_{k}'].to_numpy() for k in (21, 28, 35, 42)]), axis=0)
    f['media_mismo_dia_4'] = pd.DataFrame(mismo_dia, index=venta.index, columns=fechas)
    f['media_7_desde_16'] = _rodar(venta, 7, 'mean').shift(HORIZONTE, axis=1)
    f['media_28_desde_16'] = _rodar(venta, 28, 'mean').shift(HORIZONTE, axis=1)
    f['std_28_desde_16'] = _rodar(venta, 28, 'std').shift(HORIZONTE, axis=1)
    f['frac_ceros_28_desde_16'] = _rodar(ceros, 28, 'mean').shift(HORIZONTE, axis=1)
    f['dias_sin_venta_16'] = dias_sin_venta.shift(HORIZONTE, axis=1)
    f['nivel_serie_16'] = venta.T.expanding(min_periods=7).mean().T.shift(HORIZONTE, axis=1)
    f['transacciones_lag_16'] = transacciones.shift(HORIZONTE, axis=1)

    largo = pd.concat({nombre: ancho.stack() for nombre, ancho in f.items()}, axis=1)
    d = d.join(largo[DERIVADAS], on=CLAVE)

    for c in YA_LISTAS + PROMOCION:
        d[c] = d[c].astype('int8')
    for c in CATEGORICAS:
        d[c] = d[c].astype(str)
    return d[d['DATE'] >= INICIO_MODELADO].reset_index(drop=True)


def dividir(datos, columnas_extra=(), inicio_prueba=INICIO_PRUEBA, con_promocion=False):
    """Entrenamiento: todo lo anterior a inicio_prueba. Prueba: los 16 días
    desde inicio_prueba. División temporal, nunca aleatoria: el modelo se usa
    para predecir el futuro. columnas_extra se agregan a X pero la preparación
    las descarta (útiles para analizar errores por familia, etc.)."""
    inicio = pd.Timestamp(inicio_prueba)
    fin = inicio + pd.Timedelta(days=HORIZONTE - 1)
    columnas = NUMERICAS + YA_LISTAS + CATEGORICAS + (PROMOCION if con_promocion else []) + list(columnas_extra)
    ent = datos['DATE'] < inicio
    prueba = datos['DATE'].between(inicio, fin)
    return (datos.loc[ent, columnas], datos.loc[prueba, columnas],
            datos.loc[ent, OBJETIVO], datos.loc[prueba, OBJETIVO])


def preparacion(con_promocion=False):
    """ColumnTransformer con imputación, escalado y one-hot. Ajustes, justificados en el notebook 02:
    - numéricas: el imputador agrega indicadores de faltante (series jóvenes sin rezagos);
    - categóricas: las categorías con < 0,1 % de las filas se agrupan en 'infrecuente'
      (ITEM_CLASS tiene 95 clases, varias con pocas series)."""
    return ColumnTransformer([
        ('numericas', Pipeline([
            ('imputar', SimpleImputer(strategy='median', add_indicator=True)),
            ('escalar', StandardScaler()),
        ]), NUMERICAS),
        ('ya_listas', 'passthrough', YA_LISTAS + (PROMOCION if con_promocion else [])),
        ('categoricas', Pipeline([
            ('imputar', SimpleImputer(strategy='most_frequent')),
            ('codificar', OneHotEncoder(handle_unknown='infrequent_if_exist', min_frequency=0.001,
                                        sparse_output=False)),
        ]), CATEGORICAS),
    ])


def rmsle(y, prediccion):
    """Raíz del error cuadrático medio en escala log1p (métrica técnica del PSet 1).
    Las predicciones negativas se recortan a 0, como se haría al pedir."""
    p = np.clip(np.asarray(prediccion, dtype=float), 0, None)
    return float(np.sqrt(np.mean((np.log1p(np.asarray(y, dtype=float)) - np.log1p(p)) ** 2)))


def sesgo(y, prediccion):
    """Error medio en unidades (predicho − real): > 0 sobrestima, < 0 subestima."""
    p = np.clip(np.asarray(prediccion, dtype=float), 0, None)
    return float(np.mean(p - np.asarray(y, dtype=float)))


# Métricas de la validación cruzada. sklearn maximiza: los errores van con signo negativo.
METRICAS = {
    'rmsle': make_scorer(rmsle, greater_is_better=False),
    'mae': 'neg_mean_absolute_error',
    'sesgo': make_scorer(sesgo),
}


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

N_PLIEGUES = 5


def pliegues(X, n_splits=N_PLIEGUES):
    """Validación temporal: TimeSeriesSplit sobre las FECHAS, no sobre las filas.

    Cada pliegue valida 16 días consecutivos (el horizonte del negocio) y entrena
    con todo lo anterior (ventana creciente). Las filas de un mismo día quedan
    siempre del mismo lado, así ninguna serie aporta su futuro al entrenamiento.
    Devuelve una lista de (índices de entrenamiento, índices de validación), que
    se pasa como cv= a cross_validate o RandomizedSearchCV.
    """
    fechas = pd.Series(pd.to_datetime(X['DATE']).to_numpy())
    unicas = np.sort(fechas.unique())
    esquema = TimeSeriesSplit(n_splits=n_splits, test_size=HORIZONTE)
    resultado = []
    for ent, val in esquema.split(unicas):
        resultado.append((np.flatnonzero(fechas.isin(unicas[ent]).to_numpy()),
                          np.flatnonzero(fechas.isin(unicas[val]).to_numpy())))
    return resultado


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

def deshacer_log(z):
    """Inversa de log1p con piso en 0: una venta pronosticada no puede ser negativa."""
    return np.expm1(np.maximum(z, 0))


def en_escala_log(modelo):
    """Entrena el modelo sobre log1p(y) y devuelve unidades (hallazgo 1 del EDA).
    Minimizar el error cuadrático en log1p es minimizar directamente el RMSLE."""
    return TransformedTargetRegressor(regressor=modelo, func=np.log1p, inverse_func=deshacer_log)


def _a_arreglos(serie):
    """Series de pandas (índice de uno o más niveles) → dict de arreglos de numpy.
    Los estimadores propios guardan así lo aprendido: skops, el formato seguro de
    MLflow para scikit-learn, no serializa objetos de pandas."""
    marco = serie.reset_index()
    return {c: (marco[c].to_numpy().astype(str) if marco[c].dtype == object else marco[c].to_numpy())
            for c in marco.columns}


def _a_serie(arreglos, valor):
    marco = pd.DataFrame(arreglos)
    return marco.set_index([c for c in marco.columns if c != valor])[valor]


class ReglaSemanal(BaseEstimator, RegressorMixin):
    """Línea base de negocio del PSet 1, como estimador de scikit-learn.

    'ultima_semana' (regla principal): para cada día del horizonte, la venta del
        mismo día de la semana en la última semana antes del corte; se repite esa
        semana en los 16 días.
    'media_28': la media de los últimos 28 días antes del corte, para todos los días.

    El corte es la última fecha del entrenamiento: en cada pliegue de la CV, el día
    anterior a la ventana de validación. Respaldo para series sin ese dato: media
    histórica de la serie, luego de la familia en la tienda, luego la global.
    X debe traer STORE_NBR, ITEM_NBR, DATE y FAMILY (dividir con columnas_extra=SERIE + ['DATE']).
    """

    def __init__(self, regla='ultima_semana'):
        self.regla = regla

    def fit(self, X, y):
        d = X[SERIE + ['DATE', 'FAMILY']].assign(y=np.asarray(y, dtype=float))
        d['DATE'] = pd.to_datetime(d['DATE'])
        corte = d['DATE'].max()
        if self.regla == 'ultima_semana':
            ventana = d[d['DATE'] > corte - pd.Timedelta(days=7)]
            tabla = ventana.assign(dia=ventana['DATE'].dt.dayofweek).groupby(SERIE + ['dia'])['y'].mean()
        elif self.regla == 'media_28':
            ventana = d[d['DATE'] > corte - pd.Timedelta(days=28)]
            tabla = ventana.groupby(SERIE)['y'].mean()
        else:
            raise ValueError(f'regla desconocida: {self.regla}')
        self.corte_ = str(corte.date())
        self.tabla_ = _a_arreglos(tabla)
        self.media_serie_ = _a_arreglos(d.groupby(SERIE)['y'].mean())
        self.media_familia_ = _a_arreglos(d.groupby(['STORE_NBR', 'FAMILY'])['y'].mean())
        self.media_global_ = float(d['y'].mean())
        return self

    def predict(self, X):
        d = X[SERIE + ['DATE', 'FAMILY']].copy()
        d['DATE'] = pd.to_datetime(d['DATE'])
        d['dia'] = d['DATE'].dt.dayofweek
        llave = SERIE + ['dia'] if self.regla == 'ultima_semana' else SERIE
        p = d.join(_a_serie(self.tabla_, 'y').rename('p'), on=llave)['p']
        p = p.fillna(d.join(_a_serie(self.media_serie_, 'y').rename('m'), on=SERIE)['m'])
        p = p.fillna(d.join(_a_serie(self.media_familia_, 'y').rename('m'), on=['STORE_NBR', 'FAMILY'])['m'])
        return p.fillna(self.media_global_).clip(lower=0).to_numpy()


# Tamaños de Chronos-Bolt con la revisión fija de sus pesos en Hugging Face.
CHRONOS_TAMANOS = {
    'tiny': ('amazon/chronos-bolt-tiny', 'a0e552de83495b5c28c14c71c374f3e33280b340'),     # 9 M parámetros
    'mini': ('amazon/chronos-bolt-mini', '251268337516a88e253628c43e1d26ec577b376b'),     # 21 M
    'small': ('amazon/chronos-bolt-small', '772f3d25d38aec6d914c8949dab4462e2d46f5d8'),   # 48 M
    'base': ('amazon/chronos-bolt-base', '5d9f166d69f47aef3401367a7b842e78fe97b121'),     # 205 M
}
CHRONOS, CHRONOS_REVISION = CHRONOS_TAMANOS['small']


class ChronosBolt(BaseEstimator, RegressorMixin):
    """Modelo fundacional de series de tiempo (Chronos-Bolt), sin reentrenar (zero-shot).

    fit() no ajusta pesos: guarda la historia de ventas de cada serie hasta el
    corte (la última fecha del entrenamiento). predict() le da esa historia al
    modelo preentrenado y devuelve el cuantil pedido para cada fila de X, que
    debe caer dentro de los 64 días siguientes al corte. Así entra en
    cross_validate con los mismos pliegues y la misma métrica que el resto.
    X debe traer STORE_NBR, ITEM_NBR y DATE. Los pesos no se guardan con el
    estimador: se descargan de Hugging Face con la revisión fija.

    Hiperparámetros de inferencia (no se reentrena nada):
    cuantil   cuantil del pronóstico que se devuelve (0.5 = mediana).
    contexto  días de historia que recibe el modelo (None = toda la disponible).
    escala    'unidades' o 'log1p': en 'log1p' el modelo ve log1p(y) y el
              pronóstico se devuelve con expm1, la escala en que se mide el RMSLE.
    """

    def __init__(self, cuantil=0.5, modelo=CHRONOS, revision=CHRONOS_REVISION, contexto=None,
                 escala='unidades'):
        self.cuantil = cuantil
        self.modelo = modelo
        self.revision = revision
        self.contexto = contexto
        self.escala = escala

    def fit(self, X, y):
        d = X[SERIE + ['DATE']].assign(y=np.asarray(y, dtype=float))
        d['DATE'] = pd.to_datetime(d['DATE'])
        fechas = pd.date_range(d['DATE'].min(), d['DATE'].max(), freq='D')
        ancho = d.pivot_table(index=SERIE, columns='DATE', values='y').reindex(columns=fechas)
        self.corte_ = str(fechas[-1].date())
        self.series_ = ancho.index.to_frame(index=False).to_numpy(dtype=np.int64)
        self.historia_ = ancho.to_numpy(dtype=np.float32)   # series × días; NaN antes del inicio
        return self

    def __getstate__(self):
        estado = self.__dict__.copy()
        estado.pop('_red', None)            # los pesos no viajan con el estimador
        return estado

    def _cargar(self):
        if getattr(self, '_red', None) is None:
            import torch
            from chronos import BaseChronosPipeline
            self._red = BaseChronosPipeline.from_pretrained(
                self.modelo, revision=self.revision, device_map='cpu', torch_dtype=torch.float32)
        return self._red

    def predict(self, X):
        import torch
        d = X[SERIE + ['DATE']].copy()
        d['DATE'] = pd.to_datetime(d['DATE'])
        paso = (d['DATE'] - pd.Timestamp(self.corte_)).dt.days
        if paso.min() < 1:
            raise ValueError('Chronos solo pronostica fechas posteriores al corte del entrenamiento')
        largo = int(paso.max())
        series = d[SERIE].drop_duplicates()
        posicion = pd.Series(np.arange(len(self.series_)),
                             index=pd.MultiIndex.from_arrays(list(self.series_.T), names=SERIE))
        filas = posicion.reindex(pd.MultiIndex.from_frame(series)).to_numpy()
        contextos = []
        for fila in filas:
            historia = self.historia_[int(fila)] if not np.isnan(fila) else np.array([], np.float32)
            observados = np.flatnonzero(~np.isnan(historia))
            # Desde el primer día de la serie; un NaN interno lo trata Chronos como faltante.
            historia = historia[observados[0]:] if len(observados) else np.zeros(1, np.float32)
            if self.contexto:
                historia = historia[-int(self.contexto):]
            if self.escala == 'log1p':
                historia = np.log1p(np.maximum(historia, 0))
            contextos.append(torch.tensor(historia))
        cuantiles, _ = self._cargar().predict_quantiles(
            contextos, prediction_length=largo, quantile_levels=[self.cuantil])
        valores = cuantiles[..., 0].numpy()
        if self.escala == 'log1p':
            valores = np.expm1(valores)
        tabla = pd.DataFrame(valores, index=pd.MultiIndex.from_frame(series),
                             columns=np.arange(1, largo + 1))
        largo_tabla = tabla.stack().rename('p')
        largo_tabla.index = largo_tabla.index.set_names(SERIE + ['paso'])
        p = d.assign(paso=paso).join(largo_tabla, on=SERIE + ['paso'])['p']
        return p.clip(lower=0).to_numpy()
