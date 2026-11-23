"""Alertas, diagnóstico de la deriva y disparadores del reentrenamiento (monitoreo/alertas.py).
Usan una referencia de CV fija para no depender del archivo generado."""

from monitoreo.alertas import diagnosticar, disparar_reentrenamiento, evaluar_alertas
from monitoreo.deriva import calidad_datos

REFERENCIA = {'perdida_cuantil': {'media': 1.69, 'desviacion': 0.06},
              'perdida_cuantil_relativa': {'media': 0.216, 'desviacion': 0.0127}}   # umbral relativo 0,2414
NORMAL = {'psi_max': 0.03, 'problemas_calidad': 0, 'latencia_p95_ms': 300,
          'tasa_errores_cliente': 0.0, 'tasa_errores_servidor': 0.0}


def nombres(metricas):
    return {a['alerta'] for a in evaluar_alertas(metricas, REFERENCIA)}


def test_un_lote_normal_no_dispara_alertas():
    assert nombres(NORMAL) == set()
    assert nombres({'perdida_cuantil_relativa': 0.20, 'ahorro_vs_regla_pct': 25.0}) == set()


def test_cada_problema_dispara_su_alerta():
    assert nombres({**NORMAL, 'psi_max': 2.4}) == {'deriva_datos'}
    assert nombres({**NORMAL, 'psi_max': 0.12}) == {'deriva_datos_moderada'}
    assert nombres({**NORMAL, 'problemas_calidad': 3, 'tasa_errores_cliente': 3 / 11}) == \
        {'calidad_datos', 'errores_cliente'}
    assert nombres({'perdida_cuantil_relativa': 0.30, 'ahorro_vs_regla_pct': -5.0}) == {'desempeno', 'negocio'}


def test_diagnostico_de_la_tabla_de_deriva():
    assert diagnosticar(0.03, 0.20, REFERENCIA)[0] == 'sin deriva'
    assert diagnosticar(2.40, 0.20, REFERENCIA)[0] == 'deriva de datos sin impacto'
    assert diagnosticar(0.25, 0.30, REFERENCIA)[0] == 'deriva de datos con impacto'
    assert diagnosticar(0.04, 0.30, REFERENCIA)[0] == 'deriva conceptual'


def test_la_deriva_sin_caida_de_desempeno_no_reentrena():
    historial = [{'lote': k, 'evaluado_en_paso': k + 2, 'perdida_cuantil_relativa': 0.20} for k in (1, 2, 3)]
    assert disparar_reentrenamiento(historial, 5, referencia=REFERENCIA) is None


def test_dos_lotes_seguidos_sobre_el_umbral_reentrenan_una_sola_vez():
    historial = [{'lote': 4, 'evaluado_en_paso': 6, 'perdida_cuantil_relativa': 0.20},
                 {'lote': 5, 'evaluado_en_paso': 7, 'perdida_cuantil_relativa': 0.30}]
    assert disparar_reentrenamiento(historial, 7, referencia=REFERENCIA) is None        # un solo lote alto
    historial.append({'lote': 6, 'evaluado_en_paso': 9, 'perdida_cuantil_relativa': 0.29})
    assert 'lotes 5 y 6' in disparar_reentrenamiento(historial, 9, referencia=REFERENCIA)
    # Después del reentrenamiento del paso 9 se vuelve a contar desde cero.
    historial.append({'lote': 7, 'evaluado_en_paso': 10, 'perdida_cuantil_relativa': 0.28})
    assert disparar_reentrenamiento(historial, 10, ultimo_reentrenamiento=9, referencia=REFERENCIA) is None


def test_el_calendario_reentrena_cada_cuatro_lotes_mientras_quedan_lotes():
    assert disparar_reentrenamiento([], 4, referencia=REFERENCIA).startswith('calendario')
    assert disparar_reentrenamiento([], 3, referencia=REFERENCIA) is None
    assert disparar_reentrenamiento([], 12, n_lotes=10, referencia=REFERENCIA) is None


def test_calidad_cuenta_faltantes_obligatorios_rangos_y_categorias():
    contrato = {'numericas': {'nivel_serie_16': {'min': 0, 'max': 11.51, 'admite_nulo': True},
                              'DAY_OF_MONTH': {'min': 1, 'max': 31, 'admite_nulo': False}},
                'ya_listas': ['IS_HOLIDAY'], 'categoricas': {'FAMILY': ['DAIRY', 'EGGS']}}
    filas = [{'nivel_serie_16': None, 'DAY_OF_MONTH': 5, 'IS_HOLIDAY': 0, 'FAMILY': 'DAIRY'},     # nulo admitido
             {'nivel_serie_16': 15.0, 'DAY_OF_MONTH': None, 'IS_HOLIDAY': 1, 'FAMILY': 'JUGUETES'}]
    calidad = calidad_datos(contrato, filas)
    assert calidad['faltantes_obligatorios'] == 1
    assert calidad['fuera_de_rango_total'] == 1 and calidad['categorias_no_vistas_total'] == 1
