"""Monitoreo por lote, alertas y disparadores del reentrenamiento (PSet 4, secciones 6 y 7.1).

    python -m monitoreo.alertas <paso>     # lo que corre el flujo de Kestra monitoreo.yml
    from monitoreo.alertas import ALERTAS, evaluar_alertas, diagnosticar, disparar_reentrenamiento

En el paso k de la simulación (el día en que se predice el lote k):
1. lote k: métricas de sistema (registro de solicitudes de la API), de modelo (predicciones
   servidas) y de datos (PSI, KS / chi-cuadrado y calidad contra el contrato) → fila de MONITOREO;
2. lotes cuyo target llegó en este paso (DESEMPENO.EVALUADO_EN_LOTE = k): su desempeño se
   agrega a su fila de MONITOREO, con el diagnóstico de la tabla de la sección 6.2;
3. las alertas disparadas quedan en ALERTAS y en el log de Kestra;
4. si corresponde reentrenar, el motivo sale como output de la tarea para el flujo.

Cada alerta sigue la plantilla métrica · umbral · ventana · severidad · quién la recibe ·
acción. Los umbrales de desempeño salen de la validación cruzada del champion
(monitoreo/referencia_cv.json, que genera `python -m src.reentrenar referencia_cv`) y los
de deriva, de los lotes sin alterar (PSI máximo ≤ 0,043 en los lotes 1, 2 y 4).

Hay dos métricas técnicas por lote:
- perdida_cuantil: la pérdida cuantil 0,75, en unidades. Sube si el modelo empeora, pero
  también si la demanda crece, aunque el modelo acierte igual en proporción.
- perdida_cuantil_relativa: la misma pérdida dividida por la venta media del lote. No
  depende del volumen: es la que decide la deriva conceptual y el reentrenamiento.

Disparadores del reentrenamiento (7.1):
- por desempeño: la pérdida relativa supera la media de la CV más 2 desviaciones en
  N_LOTES_DESEMPENO lotes consecutivos con target, contados desde el último reentrenamiento
  (sin esa condición, una deriva que dura dispararía un reentrenamiento en cada paso);
- por calendario: cada CADA_N_LOTES pasos con lote nuevo, aunque no haya alertas.
La deriva de datos sin caída de desempeño no dispara el reentrenamiento, y el
reentrenamiento solo usa lotes cuyo target ya llegó.
"""

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from monitoreo.deriva import UMBRAL_PSI, UMBRAL_PSI_MODERADO  # noqa: E402

RUTA_REFERENCIA_CV = Path(__file__).parent / 'referencia_cv.json'
RUTA_SOLICITUDES = os.environ.get('RUTA_SOLICITUDES', '/registros/solicitudes.jsonl')
N_DESVIACIONES = 2
N_LOTES_DESEMPENO = 2
CADA_N_LOTES = 4
LATENCIA_P95_MAX_MS = 500         # por petición de 2.000 filas (medida: p50 ≈ 160 ms, p95 ≈ 300 ms)
TASA_ERRORES_SERVIDOR_MAX = 0.01
TASA_ERRORES_CLIENTE_MAX = 0.01


def referencia_cv(ruta=RUTA_REFERENCIA_CV):
    return json.loads(Path(ruta).read_text(encoding='utf-8'))


def umbrales(referencia=None):
    """Umbrales de desempeño: media de la CV + N_DESVIACIONES desviaciones (pérdidas) y
    ahorro negativo frente a la regla (el modelo cuesta más que la línea base)."""
    referencia = referencia or referencia_cv()
    return {m: referencia[m]['media'] + N_DESVIACIONES * referencia[m]['desviacion']
            for m in ('perdida_cuantil', 'perdida_cuantil_relativa')} | {'ahorro_vs_regla_pct': 0.0}


def _mayor(clave, umbral):
    return lambda m, u: m.get(clave) is not None and m[clave] > (u[umbral] if isinstance(umbral, str) else umbral)


# Plantilla de la sección 6.3. 'clave' es la métrica del lote que se compara; 'cuando', la condición.
ALERTAS = [
    {'alerta': 'deriva_datos', 'clave': 'psi_max', 'metrica': 'PSI máximo de las features vigiladas',
     'umbral': f'> {UMBRAL_PSI}', 'ventana': '1 lote', 'severidad': 'alta', 'recibe': 'equipo de datos',
     'accion': 'revisar la fuente; si el desempeño también cae, evaluar reentrenamiento',
     'cuando': _mayor('psi_max', UMBRAL_PSI)},
    {'alerta': 'deriva_datos_moderada', 'clave': 'psi_max', 'metrica': 'PSI máximo de las features vigiladas',
     'umbral': f'{UMBRAL_PSI_MODERADO} a {UMBRAL_PSI}', 'ventana': '1 lote', 'severidad': 'baja',
     'recibe': 'equipo de datos', 'accion': 'aviso: vigilar el lote siguiente',
     'cuando': lambda m, u: m.get('psi_max') is not None and UMBRAL_PSI_MODERADO < m['psi_max'] <= UMBRAL_PSI},
    {'alerta': 'calidad_datos', 'clave': 'problemas_calidad',
     'metrica': 'faltantes en campos obligatorios + valores fuera de rango + categorías no vistas',
     'umbral': '> 0', 'ventana': '1 lote', 'severidad': 'media', 'recibe': 'equipo de datos',
     'accion': 'revisar la fuente; la API ya rechazó esas filas (422) y no tienen pedido',
     'cuando': _mayor('problemas_calidad', 0)},
    {'alerta': 'desempeno', 'clave': 'perdida_cuantil_relativa', 'metrica': 'pérdida cuantil relativa (pérdida / venta media)',
     'umbral': f'> media CV + {N_DESVIACIONES} desv.', 'ventana': '1 lote con target', 'severidad': 'alta',
     'recibe': 'equipo de ciencia de datos',
     'accion': f'diagnosticar la deriva; con {N_LOTES_DESEMPENO} lotes seguidos se dispara el reentrenamiento',
     'cuando': _mayor('perdida_cuantil_relativa', 'perdida_cuantil_relativa')},
    {'alerta': 'negocio', 'clave': 'ahorro_vs_regla_pct', 'metrica': 'ahorro frente a la regla de negocio (%)',
     'umbral': '< 0', 'ventana': '1 lote con target', 'severidad': 'crítica',
     'recibe': 'jefatura de operaciones y ciencia de datos',
     'accion': 'el modelo cuesta más que la regla: evaluar el interruptor de respaldo (criterio de retirada)',
     'cuando': lambda m, u: m.get('ahorro_vs_regla_pct') is not None and m['ahorro_vs_regla_pct'] < 0},
    {'alerta': 'latencia', 'clave': 'latencia_p95_ms', 'metrica': 'latencia p95 del servicio (ms por petición)',
     'umbral': f'> {LATENCIA_P95_MAX_MS}', 'ventana': '1 lote', 'severidad': 'media', 'recibe': 'equipo de plataforma',
     'accion': 'revisar recursos del contenedor; el lote puede repetirse',
     'cuando': _mayor('latencia_p95_ms', LATENCIA_P95_MAX_MS)},
    {'alerta': 'errores_servidor', 'clave': 'tasa_errores_servidor', 'metrica': 'tasa de errores 5xx',
     'umbral': f'> {TASA_ERRORES_SERVIDOR_MAX:.0%}', 'ventana': '1 lote', 'severidad': 'alta',
     'recibe': 'equipo de plataforma', 'accion': 'revisar el servicio; si el modelo no carga, responde la regla de respaldo',
     'cuando': _mayor('tasa_errores_servidor', TASA_ERRORES_SERVIDOR_MAX)},
    {'alerta': 'errores_cliente', 'clave': 'tasa_errores_cliente', 'metrica': 'tasa de errores 4xx',
     'umbral': f'> {TASA_ERRORES_CLIENTE_MAX:.0%}', 'ventana': '1 lote', 'severidad': 'media', 'recibe': 'equipo de datos',
     'accion': 'revisar qué campos rechaza el contrato y la fuente que los produce',
     'cuando': _mayor('tasa_errores_cliente', TASA_ERRORES_CLIENTE_MAX)},
]

# Tabla de la sección 6.2: (entradas cambian, desempeño cae) → diagnóstico y acción.
DIAGNOSTICOS = {
    (False, False): ('sin deriva', 'ninguna'),
    (True, False): ('deriva de datos sin impacto', 'revisar la fuente y documentar; no se reentrena'),
    (True, True): ('deriva de datos con impacto', 'revisar la fuente y reentrenar con los lotes recientes '
                                                  '(disparador por desempeño)'),
    (False, True): ('deriva conceptual', 'reentrenar con ventana reciente; si no mejora, '
                                         'revisar las features y el juicio humano'),
}


def tabla_alertas():
    """La plantilla de 6.3 sin las condiciones, para el documento y el tablero."""
    return [{k: v for k, v in a.items() if k not in ('cuando', 'clave')} for a in ALERTAS]


def evaluar_alertas(metricas, referencia=None):
    """Las alertas que dispara un lote, con el valor que la disparó. Las métricas de
    desempeño solo existen cuando ya llegó el target del lote."""
    u = umbrales(referencia)
    return [{**{k: a[k] for k in ('alerta', 'metrica', 'umbral', 'severidad', 'recibe', 'accion')},
             'valor': metricas.get(a['clave'])}
            for a in ALERTAS if a['cuando'](metricas, u)]


def diagnosticar(psi_max, perdida_relativa, referencia=None):
    """Diagnóstico y acción de la tabla de 6.2 para un lote con target."""
    cambian = psi_max is not None and psi_max > UMBRAL_PSI
    cae = perdida_relativa is not None and perdida_relativa > umbrales(referencia)['perdida_cuantil_relativa']
    return DIAGNOSTICOS[(cambian, cae)]


def disparar_reentrenamiento(historial, paso, ultimo_reentrenamiento=0, n_lotes=10, referencia=None):
    """Motivo del reentrenamiento en el paso `paso`, o None.

    `historial`: dicts con 'lote', 'evaluado_en_paso' y 'perdida_cuantil_relativa' de los lotes
    con target, en orden. Desempeño: los últimos N_LOTES_DESEMPENO lotes evaluados después del
    paso `ultimo_reentrenamiento` superan el umbral. Calendario: `paso` es múltiplo de
    CADA_N_LOTES y todavía hay lotes por predecir."""
    u = umbrales(referencia)['perdida_cuantil_relativa']
    recientes = [h for h in historial if h['evaluado_en_paso'] > ultimo_reentrenamiento
                 and h.get('perdida_cuantil_relativa') is not None][-N_LOTES_DESEMPENO:]
    motivos = []
    if len(recientes) == N_LOTES_DESEMPENO and all(h['perdida_cuantil_relativa'] > u for h in recientes):
        motivos.append(f'desempeño: pérdida relativa > {u:.4f} en los lotes '
                       + ' y '.join(str(h['lote']) for h in recientes))
    if paso % CADA_N_LOTES == 0 and paso < n_lotes:
        motivos.append(f'calendario: cada {CADA_N_LOTES} lotes (paso {paso})')
    return '; '.join(motivos) or None


# --------------------------------------------------------------------------- #
# Monitoreo de un paso (Snowflake)
# --------------------------------------------------------------------------- #
def metricas_sistema(identificador, ruta=RUTA_SOLICITUDES):
    """Peticiones, errores y latencia de las solicitudes de la API con ese identificador de lote."""
    import numpy as np

    solicitudes = []
    with open(ruta, encoding='utf-8') as archivo:
        for linea in archivo:
            if identificador in linea:
                s = json.loads(linea)
                if s.get('lote') == identificador:
                    solicitudes.append(s)
    if not solicitudes:
        return {}
    codigos = np.array([s['codigo'] for s in solicitudes])
    latencias = np.array([s['latencia_ms'] for s in solicitudes])
    cliente, servidor = int(((codigos >= 400) & (codigos < 500)).sum()), int((codigos >= 500).sum())
    return {'peticiones': len(solicitudes), 'productos': int(sum(s['productos'] or 0 for s in solicitudes)),
            'errores_cliente': cliente, 'errores_servidor': servidor,
            'tasa_errores_cliente': cliente / len(solicitudes), 'tasa_errores_servidor': servidor / len(solicitudes),
            'latencia_p50_ms': float(np.percentile(latencias, 50)), 'latencia_p95_ms': float(np.percentile(latencias, 95))}


def ultimo_reentrenamiento(cur, paso):
    """Paso del último reentrenamiento anterior a `paso` (0 si no hubo o si la tabla no existe)."""
    try:
        cur.execute('SELECT COALESCE(MAX(PASO), 0) FROM REENTRENAMIENTOS WHERE PASO < %s', (paso,))
        return int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001 — todavía no hay reentrenamientos
        return 0


def monitorear(paso):
    import pandas as pd
    from snowflake.connector.pandas_tools import write_pandas

    from monitoreo.deriva import RUTA_MUESTRA_REFERENCIA, calidad_datos, psi_por_feature, pruebas_estadisticas
    from src.datos import conectar
    from src.lotes import ESQUEMA, N_LOTES, leer_lote
    from src.produccion import etiqueta, fecha_del_paso

    fecha = fecha_del_paso(paso)
    referencia = referencia_cv()
    alertas = []
    with conectar('PSET4_MONITOREO') as con, con.cursor() as cur:
        cur.execute(f'USE SCHEMA {ESQUEMA}')

        # 1. El lote recién predicho.
        if paso <= N_LOTES:
            cur.execute("""SELECT EJECUCION FROM PREDICCIONES WHERE LOTE = %s
                           GROUP BY EJECUCION ORDER BY MAX(FECHA_HORA) DESC LIMIT 1""", (paso,))
            fila = cur.fetchone()
            ejecucion = fila[0] if fila else None
            datos = leer_lote(paso, con)
            contrato = json.loads((RAIZ / 'api' / 'contrato.json').read_text(encoding='utf-8'))
            deriva = json.loads((RAIZ / 'api' / 'referencia_deriva.json').read_text(encoding='utf-8'))
            psi = psi_por_feature(deriva, datos)
            pruebas = pruebas_estadisticas(pd.read_parquet(RUTA_MUESTRA_REFERENCIA), datos)
            calidad = calidad_datos(contrato, datos)
            sistema = metricas_sistema(etiqueta(paso, ejecucion)) if ejecucion else {}
            cur.execute("""SELECT ANY_VALUE(VERSION_MODELO), AVG(PEDIDO), MEDIAN(PEDIDO),
                                  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY PEDIDO),
                                  AVG(IFF(DECISION = 'reponer', 1, 0)), 100 * AVG(IFF(USO_RESPALDO, 1, 0))
                           FROM PREDICCIONES WHERE EJECUCION = %s""", (ejecucion,))
            version, pedido_medio, pedido_p50, pedido_p95, tasa_reponer, respaldo = cur.fetchone()
            feature_max = max(psi, key=psi.get)
            metricas = {**sistema, 'psi_max': psi[feature_max],
                        'problemas_calidad': calidad['faltantes_obligatorios'] + calidad['fuera_de_rango_total']
                        + calidad['categorias_no_vistas_total']}
            fila_monitoreo = {
                'LOTE': paso, 'PASO': paso, 'FECHA_PASO': fecha, 'EJECUCION': ejecucion,
                **{k.upper(): sistema.get(k) for k in ('peticiones', 'productos', 'errores_cliente', 'errores_servidor',
                                                       'tasa_errores_cliente', 'tasa_errores_servidor',
                                                       'latencia_p50_ms', 'latencia_p95_ms')},
                'VERSION_MODELO': version, 'PEDIDO_MEDIO': pedido_medio, 'PEDIDO_P50': pedido_p50,
                'PEDIDO_P95': pedido_p95, 'TASA_REPONER': tasa_reponer, 'USO_RESPALDO_PCT': respaldo,
                'FILAS_LOTE': calidad['filas'], 'FALTANTES_MAX': calidad['faltantes_max'],
                'FALTANTES_OBLIGATORIOS': calidad['faltantes_obligatorios'],
                'FUERA_DE_RANGO_TOTAL': calidad['fuera_de_rango_total'],
                'CATEGORIAS_NO_VISTAS_TOTAL': calidad['categorias_no_vistas_total'],
                'PSI_MAX': psi[feature_max], 'FEATURE_PSI_MAX': feature_max,
                'PSI': json.dumps(psi), 'PRUEBAS': json.dumps(pruebas), 'CALIDAD': json.dumps(calidad)}
            cur.execute('DELETE FROM MONITOREO WHERE LOTE = %s', (paso,))
            write_pandas(con, pd.DataFrame([fila_monitoreo]), 'MONITOREO_CARGA', auto_create_table=True,
                         table_type='temporary', quote_identifiers=False, overwrite=True)
            columnas = list(fila_monitoreo)
            cur.execute(f'INSERT INTO MONITOREO ({", ".join(columnas)}) SELECT '
                        + ', '.join(f'PARSE_JSON({c})' if c in ('PSI', 'PRUEBAS', 'CALIDAD') else c for c in columnas)
                        + ' FROM MONITOREO_CARGA')
            alertas += [{'LOTE': paso, **a} for a in evaluar_alertas(metricas, referencia)]
            print(f'Lote {paso}: PSI máximo {psi[feature_max]:.3f} ({feature_max}), '
                  f'calidad {metricas["problemas_calidad"]}, sistema {json.dumps(sistema)}')

        # 2. Los lotes cuyo target llegó en este paso.
        cur.execute("""SELECT d.LOTE, d.PERDIDA_CUANTIL, d.PERDIDA_CUANTIL_RELATIVA, d.AHORRO_VS_REGLA_PCT,
                              d.COSTO, d.COSTO_REGLA, m.PSI_MAX
                       FROM DESEMPENO d LEFT JOIN MONITOREO m USING (LOTE)
                       WHERE d.EVALUADO_EN_LOTE = %s ORDER BY d.LOTE""", (paso,))
        for lote, perdida, relativa, ahorro, costo, costo_regla, psi_max in cur.fetchall():
            diagnostico, accion = diagnosticar(psi_max, relativa, referencia)
            cur.execute("""UPDATE MONITOREO SET EVALUADO_EN_PASO = %s, PERDIDA_CUANTIL = %s,
                           PERDIDA_CUANTIL_RELATIVA = %s, AHORRO_VS_REGLA_PCT = %s, COSTO = %s, COSTO_REGLA = %s,
                           DIAGNOSTICO = %s WHERE LOTE = %s""",
                        (paso, perdida, relativa, ahorro, costo, costo_regla, diagnostico, lote))
            alertas += [{'LOTE': lote, **a} for a in evaluar_alertas(
                {'perdida_cuantil_relativa': relativa, 'ahorro_vs_regla_pct': ahorro}, referencia)]
            print(f'Lote {lote} con target: pérdida {perdida:.3f} (relativa {relativa:.4f}), '
                  f'ahorro vs regla {ahorro:+.1f} %, PSI {psi_max:.3f} → {diagnostico}: {accion}')

        # 3. Registro de alertas.
        cur.execute('DELETE FROM ALERTAS WHERE PASO = %s', (paso,))
        if alertas:
            tabla = pd.DataFrame([{'PASO': paso, 'FECHA_PASO': fecha, 'LOTE': a['LOTE'], 'ALERTA': a['alerta'],
                                   'METRICA': a['metrica'], 'VALOR': a['valor'], 'UMBRAL': a['umbral'],
                                   'SEVERIDAD': a['severidad'], 'RECIBE': a['recibe'], 'ACCION': a['accion']}
                                  for a in alertas])
            write_pandas(con, tabla, 'ALERTAS', quote_identifiers=False)
        for a in alertas:
            print(f"ALERTA [{a['severidad']}] lote {a['LOTE']} · {a['alerta']}: {a['metrica']} = "
                  f"{a['valor']:.4g} (umbral {a['umbral']}) → {a['recibe']}: {a['accion']}", file=sys.stderr)

        # 4. ¿Reentrenar?
        cur.execute("""SELECT LOTE, EVALUADO_EN_LOTE, PERDIDA_CUANTIL_RELATIVA FROM DESEMPENO
                       WHERE EVALUADO_EN_LOTE <= %s ORDER BY LOTE""", (paso,))
        historial = [{'lote': l, 'evaluado_en_paso': e, 'perdida_cuantil_relativa': r} for l, e, r in cur.fetchall()]
        motivo = disparar_reentrenamiento(historial, paso, ultimo_reentrenamiento(cur, paso), N_LOTES, referencia)

    print(f'Paso {paso} ({fecha}): {len(alertas)} alertas; reentrenamiento: {motivo or "no"}')
    # Kestra lee esta línea como outputs de la tarea (outputs.<tarea>.vars.*).
    print('::' + json.dumps({'outputs': {'alertas': len(alertas), 'reentrenar': motivo is not None,
                                         'motivo': motivo or ''}}) + '::')
    return alertas, motivo


if __name__ == '__main__':
    import warnings
    warnings.filterwarnings('ignore')
    if len(sys.argv) > 1:
        monitorear(int(sys.argv[1]))
    else:
        print(__doc__)
