"""Tablero de monitoreo (sección 6.4 del PSet 4): lote por lote, métricas de sistema,
de modelo, de datos y de desempeño, con las alertas y los reentrenamientos marcados.

    streamlit run tablero/app.py           # http://localhost:8501

Lee PRODUCCION.MONITOREO, ALERTAS y REENTRENAMIENTOS de Snowflake (src/datos.conectar).
Si Snowflake no responde, usa los CSV exportados en docs/ (src/exportar.py) y lo indica.

Cómo leer los gráficos
- Eje x: lote semanal (1 a 10, del 2017-06-05 al 2017-08-13).
- Línea punteada horizontal: umbral de la alerta (monitoreo/alertas.py).
- Triángulo rojo: lote con alerta disparada en esa métrica.
- Línea vertical: reentrenamiento entre dos lotes (verde = aprobado, gris = rechazado).
"""

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

ESQUEMA = 'PRODUCCION'
UMBRALES = {'psi': 0.20, 'psi_moderado': 0.10, 'perdida_relativa': 0.2415, 'ahorro': 0.0,
            'latencia_ms': 500.0, 'tasa_errores': 0.01}

# Colores (paleta de referencia de la guía de visualización): una serie por gráfico.
SERIE = '#2a78d6'
TEXTO_SECUNDARIO = '#52514e'
REJILLA = '#e1e0d9'
CRITICO = '#d03b3b'
BIEN = '#0ca30c'
NEUTRO = '#898781'
AZULES = ['#cde2fb', '#6da7ec', '#1c5cab']   # PSI < 0,10 | 0,10–0,20 | ≥ 0,20
NIVELES_PSI = ['< 0,10 (estable)', '0,10–0,20 (moderada)', '≥ 0,20 (alerta)']


# --------------------------------------------------------------------------- datos
@st.cache_data(ttl=15)
def version_api():
    """Versión que sirve la API (GET /modelo), o None si no responde."""
    import os
    import urllib.request
    try:
        with urllib.request.urlopen(os.environ.get('API_URL', 'http://api:8000') + '/modelo', timeout=2) as r:
            return str(json.load(r)['version'])
    except Exception:   # noqa: BLE001 — tablero sin API (por ejemplo, solo con los CSV)
        return None


@st.cache_data(ttl=60)
def cargar():
    """Devuelve (monitoreo, alertas, reentrenamientos, fuente)."""
    try:
        from src.datos import conectar
        with conectar('PSET4_TABLERO') as con, con.cursor() as cur:
            tablas = []
            for sql in (f'SELECT * FROM {ESQUEMA}.MONITOREO ORDER BY LOTE',
                        f'SELECT * FROM {ESQUEMA}.ALERTAS ORDER BY PASO, LOTE',
                        f'SELECT * FROM {ESQUEMA}.REENTRENAMIENTOS ORDER BY PASO'):
                cur.execute(sql)
                tablas.append(cur.fetch_pandas_all())
        return (*tablas, 'Snowflake (PSET2_DB.PRODUCCION)')
    except Exception as error:   # sin red o sin credenciales: los CSV de docs/
        docs = RAIZ / 'docs'
        leer = lambda nombre: pd.read_csv(docs / nombre, encoding='utf-8-sig')
        reentrenamientos = leer('reentrenamientos.csv')
        reentrenamientos = (reentrenamientos.dropna(subset=['decision.paso'])
                            .rename(columns=lambda c: c.replace('decision.', '').upper()))
        return (leer('monitoreo.csv'), leer('alertas.csv'), reentrenamientos,
                f'CSV de docs/ (Snowflake no respondió: {type(error).__name__})')


def psi_largo(monitoreo):
    filas = []
    for _, fila in monitoreo.iterrows():
        psi = fila['PSI'] if isinstance(fila['PSI'], dict) else json.loads(fila['PSI'] or '{}')
        filas += [{'LOTE': fila['LOTE'], 'feature': f, 'PSI': v} for f, v in psi.items()]
    largo = pd.DataFrame(filas)
    largo['nivel'] = pd.cut(largo['PSI'], [-1, UMBRALES['psi_moderado'], UMBRALES['psi'], 1e9],
                            labels=NIVELES_PSI, right=False).astype(str)
    return largo


# ------------------------------------------------------------------------ gráficos
EJE_LOTE = alt.X('LOTE:Q', title='lote', scale=alt.Scale(domain=[0.5, 10.5]),
                 axis=alt.Axis(values=list(range(1, 11)), format='d', grid=False))


def marcas_reentrenamiento(reentrenamientos):
    """Regla vertical entre el lote del paso y el siguiente: ahí ocurre el reentrenamiento."""
    if reentrenamientos.empty:
        return []
    r = reentrenamientos.assign(
        x=reentrenamientos['PASO'].astype(float) + 0.5,
        etiqueta=[f"R{int(p)} {'✓ v' + str(v) if d == 'aprobado' else '✗'}"
                  for p, d, v in zip(reentrenamientos['PASO'], reentrenamientos['DECISION'],
                                     reentrenamientos['VERSION_CHALLENGER'])])
    color = alt.condition(alt.datum.DECISION == 'aprobado', alt.value(BIEN), alt.value(NEUTRO))
    regla = alt.Chart(r).mark_rule(strokeDash=[4, 3], strokeWidth=1.5).encode(
        x='x:Q', color=color,
        tooltip=[alt.Tooltip('PASO:Q', title='paso'), alt.Tooltip('DECISION:N', title='decisión'),
                 alt.Tooltip('VERSION_CHALLENGER:N', title='challenger'),
                 alt.Tooltip('MOTIVO:N', title='disparo')])
    texto = alt.Chart(r).mark_text(align='left', dx=3, dy=-4, fontSize=10, color=TEXTO_SECUNDARIO).encode(
        x='x:Q', y=alt.value(0), text='etiqueta:N')
    return [regla, texto]


def grafico(monitoreo, alertas, reentrenamientos, campo, titulo, claves_alerta, umbral=None,
            formato='.3f', umbral_texto=None, desde_cero=True):
    datos = monitoreo[['LOTE', campo, 'DIAGNOSTICO']].dropna(subset=[campo]).copy()
    con_alerta = set(alertas.loc[alertas['ALERTA'].isin(claves_alerta), 'LOTE'])
    datos['alerta'] = datos['LOTE'].isin(con_alerta).map({True: 'sí', False: 'no'})
    eje_y = alt.Y(f'{campo}:Q', title=None, scale=alt.Scale(zero=desde_cero),
                  axis=alt.Axis(format=formato, gridColor=REJILLA))
    ayuda = [alt.Tooltip('LOTE:Q', title='lote'), alt.Tooltip(f'{campo}:Q', title=titulo, format=formato),
             alt.Tooltip('alerta:N'), alt.Tooltip('DIAGNOSTICO:N', title='diagnóstico')]
    base = alt.Chart(datos).encode(x=EJE_LOTE, y=eje_y)
    capas = [base.mark_line(color=SERIE, strokeWidth=2),
             base.mark_point(color=SERIE, filled=True, size=50).encode(tooltip=ayuda),
             base.transform_filter(alt.datum.alerta == 'sí').mark_point(
                 shape='triangle-up', color=CRITICO, filled=True, size=140).encode(tooltip=ayuda)]
    if umbral is not None:
        regla = pd.DataFrame({'y': [umbral], 'texto': [umbral_texto or f'umbral {umbral:{formato}}']})
        capas += [alt.Chart(regla).mark_rule(strokeDash=[6, 4], color=TEXTO_SECUNDARIO).encode(y='y:Q'),
                  alt.Chart(regla).mark_text(align='left', dy=-6, fontSize=10, color=TEXTO_SECUNDARIO)
                  .encode(y='y:Q', x=alt.value(4), text='texto:N')]
    capas += marcas_reentrenamiento(reentrenamientos)
    return alt.layer(*capas).properties(title=titulo, height=230, width=420)


def mapa_psi(largo):
    base = alt.Chart(largo).encode(
        x=alt.X('LOTE:O', title='lote', axis=alt.Axis(labelAngle=0)),
        y=alt.Y('feature:N', title=None, axis=alt.Axis(labelLimit=260)))
    celdas = base.mark_rect(stroke='#fcfcfb', strokeWidth=2).encode(
        color=alt.Color('nivel:N', title='PSI', scale=alt.Scale(domain=NIVELES_PSI, range=AZULES),
                        sort=NIVELES_PSI),
        tooltip=[alt.Tooltip('LOTE:O', title='lote'), 'feature:N', alt.Tooltip('PSI:Q', format='.3f')])
    valores = base.transform_filter(alt.datum.PSI >= UMBRALES['psi_moderado']).mark_text(
        fontSize=11, color='white', fontWeight='bold').encode(text=alt.Text('PSI:Q', format='.2f'))
    return (celdas + valores).properties(title='PSI por feature y lote', height=420)


# -------------------------------------------------------------------------- página
st.set_page_config(page_title='Monitoreo · pedido de perecederos', layout='wide')
monitoreo, alertas, reentrenamientos, fuente = cargar()
monitoreo['PROBLEMAS_CALIDAD'] = (monitoreo['FALTANTES_OBLIGATORIOS'].fillna(0)
                                  + monitoreo['FUERA_DE_RANGO_TOTAL'].fillna(0)
                                  + monitoreo['CATEGORIAS_NO_VISTAS_TOTAL'].fillna(0))
monitoreo['USO_RESPALDO_PCT'] = monitoreo['USO_RESPALDO_PCT'].fillna(0)

st.title('Monitoreo del pedido de perecederos')
st.caption(f'Fuente: {fuente}. Se actualiza cada 60 s. Triángulo rojo = alerta en esa métrica; '
           'línea vertical = reentrenamiento (verde aprobado, gris rechazado).')

aprobados = reentrenamientos[reentrenamientos['DECISION'] == 'aprobado']
# La versión que sirve la API (refleja también un rollback manual del alias); sin API, la
# del último reentrenamiento aprobado.
champion = version_api() or (str(aprobados['VERSION_CHALLENGER'].iloc[-1]) if len(aprobados)
                             else str(monitoreo['VERSION_MODELO'].iloc[0]))
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric('Lotes procesados', f"{monitoreo['LOTE'].nunique()} de 10")
k2.metric('Alertas', len(alertas))
k3.metric('Reentrenamientos', f'{len(reentrenamientos)} · {len(aprobados)} aprobado' + ('s' if len(aprobados) != 1 else ''))
k4.metric('Champion actual', f'versión {champion}')
k5.metric('Ahorro medio vs regla', f"{monitoreo['AHORRO_VS_REGLA_PCT'].mean():.1f} %")

args = (monitoreo, alertas, reentrenamientos)
st.header('Desempeño (cuando llega el target)')
c1, c2 = st.columns(2)
c1.altair_chart(grafico(*args, 'PERDIDA_CUANTIL_RELATIVA', 'Pérdida cuantil relativa', ['desempeno'],
                        UMBRALES['perdida_relativa'], umbral_texto='umbral 0,2415 (media CV + 2σ)', desde_cero=False),
                width='stretch')
c2.altair_chart(grafico(*args, 'AHORRO_VS_REGLA_PCT', 'Ahorro vs regla de negocio (%)', ['negocio'],
                        UMBRALES['ahorro'], formato='.1f', umbral_texto='0 % (igual a la regla)'),
                width='stretch')

st.header('Datos y deriva')
c1, c2 = st.columns(2)
c1.altair_chart(grafico(*args, 'PSI_MAX', 'PSI máximo de las features', ['deriva_datos', 'deriva_datos_moderada'],
                        UMBRALES['psi'], formato='.2f', umbral_texto='umbral 0,20'), width='stretch')
c2.altair_chart(grafico(*args, 'PROBLEMAS_CALIDAD', 'Filas con problemas de calidad', ['calidad_datos'],
                        formato='d'), width='stretch')
st.altair_chart(mapa_psi(psi_largo(monitoreo)), width='stretch')

st.header('Sistema (registro de la API)')
c1, c2 = st.columns(2)
c1.altair_chart(grafico(*args, 'LATENCIA_P95_MS', 'Latencia p95 por petición (ms)', ['latencia'],
                        UMBRALES['latencia_ms'], formato='.0f', umbral_texto='umbral 500 ms'),
                width='stretch')
c2.altair_chart(grafico(*args, 'TASA_ERRORES_CLIENTE', 'Tasa de errores 4xx', ['errores_cliente'],
                        UMBRALES['tasa_errores'], formato='.1%', umbral_texto='umbral 1 %'),
                width='stretch')

st.header('Modelo (predicciones servidas)')
c1, c2 = st.columns(2)
c1.altair_chart(grafico(*args, 'PEDIDO_MEDIO', 'Pedido sugerido medio (unidades)', [], formato='.1f'),
                width='stretch')
c2.altair_chart(grafico(*args, 'USO_RESPALDO_PCT', 'Predicciones con la regla de respaldo (%)', [],
                        formato='.1f'), width='stretch')

st.header('Registros')
with st.expander(f'Alertas ({len(alertas)})', expanded=True):
    st.dataframe(alertas[['PASO', 'LOTE', 'ALERTA', 'METRICA', 'VALOR', 'UMBRAL', 'SEVERIDAD', 'RECIBE', 'ACCION']],
                 hide_index=True, width='stretch')
with st.expander(f'Reentrenamientos ({len(reentrenamientos)})', expanded=True):
    columnas = ['PASO', 'MOTIVO', 'VERSION_CHAMPION', 'VERSION_CHALLENGER', 'LOTE_EVALUACION',
                'AHORRO_VS_REGLA_PCT_CHAMPION', 'AHORRO_VS_REGLA_PCT_CHALLENGER', 'DIFERENCIA_AHORRO_PP',
                'RECOMENDACION', 'DECISION', 'MOTIVO_DECISION', 'VERSION_CHAMPION_FINAL']
    st.dataframe(reentrenamientos[[c for c in columnas if c in reentrenamientos]], hide_index=True,
                 width='stretch')
with st.expander('Monitoreo por lote (tabla completa)'):
    st.dataframe(monitoreo.drop(columns=['PSI', 'PRUEBAS', 'CALIDAD'], errors='ignore'), hide_index=True,
                 width='stretch')
