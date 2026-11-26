"""Diagrama de arquitectura end-to-end del proyecto final -> docs/arquitectura.png

    python docs/diagramas/arquitectura.py docs/arquitectura.png
"""
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams['font.family'] = 'Arial'
TINTA = '#12364f'
SUAVE = '#4a6272'
FLECHA = '#0f6966'
TIPOS = {
    'proceso': ('#e6f2f1', '#0f6966'),
    'datos': ('#e8eef5', '#1d3f5e'),
    'servicio': ('#fdf1e3', '#a35d12'),
    'humano': ('#f8e8ec', '#9b2f4c'),
}
AN, AL = 15.5, 7.4         # ancho y alto de cada caja

fig, ax = plt.subplots(figsize=(16, 10.2))
ax.set_xlim(0, 100)
ax.set_ylim(0, 64)
ax.axis('off')


def franja(y0, y1, titulo):
    ax.add_patch(FancyBboxPatch((0.6, y0), 98.8, y1 - y0, boxstyle='round,pad=0,rounding_size=0.8',
                                fc='#f7f9fa', ec='#d5dde2', lw=0.8, zorder=0))
    ax.text(6.0, y1 - 0.8, titulo, ha='left', va='top', fontsize=11.5, color=TINTA, weight='bold')


def caja(x, y, titulo, detalle, tipo, ancho=AN, alto=AL):
    fondo, borde = TIPOS[tipo]
    ax.add_patch(FancyBboxPatch((x - ancho / 2, y - alto / 2), ancho, alto,
                                boxstyle='round,pad=0,rounding_size=0.7', fc=fondo, ec=borde, lw=1.3, zorder=2))
    ax.text(x, y + 1.35, titulo, ha='center', va='center', fontsize=11, color=TINTA, weight='bold', zorder=3)
    ax.text(x, y - 1.35, detalle, ha='center', va='center', fontsize=8.6, color=SUAVE, zorder=3,
            linespacing=1.25)
    return x, y


def flecha(puntos, texto=None, pos=None, ha='center', punteada=False, doble=False):
    xs, ys = zip(*puntos)
    for (x0, y0), (x1, y1) in zip(puntos[:-2], puntos[1:-1]):
        ax.plot([x0, x1], [y0, y1], color=FLECHA, lw=1.4, ls='--' if punteada else '-', zorder=1,
                solid_capstyle='butt')
    ax.add_patch(FancyArrowPatch(puntos[-2], puntos[-1], arrowstyle='<|-|>' if doble else '-|>',
                                 mutation_scale=13, color=FLECHA, lw=1.4, ls='--' if punteada else '-',
                                 zorder=1, shrinkA=0, shrinkB=0))
    if texto:
        ax.text(*pos, texto, ha=ha, va='center', fontsize=8.4, color=FLECHA, style='italic', zorder=3,
                bbox=dict(fc='#f7f9fa', ec='none', pad=0.6))


# --- Bandas -------------------------------------------------------------------------------------------
franja(49.5, 63.2, '1 · Datos   (Kestra pipeline_completo, diario 06:00)')
franja(33.5, 48.5, '2 · Modelo y servicio')
franja(1.0, 32.5, '3 · Producción, monitoreo\n     y reentrenamiento')
ax.text(6.0, 26.6, 'Kestra simulacion:\n10 lotes semanales', ha='left', va='center', fontsize=9, color=SUAVE)

Y1, Y2, Y3, Y4 = 54.8, 39.6, 24.0, 8.2
X = [10, 29, 48, 67, 87]

# --- 1 · Datos ----------------------------------------------------------------------------------------
caja(X[0], Y1, 'CSV de Favorita', '6 archivos de Kaggle', 'datos')
caja(X[1], Y1, 'Ingesta', 'Python → RAW\n3 intentos · backfill', 'proceso')
caja(X[2], Y1, 'dbt Core', 'Bronze → Silver → Gold\nstar schema + pruebas', 'proceso')
caja(X[3], Y1, 'Spark 3.5.3', 'Gold → OBT\nsolo publica si cuadra', 'proceso')
caja(X[4], Y1, 'OBT en Snowflake', 'ANALYTICS.OBT_SALES\n13.017.002 filas', 'datos')
for a, b in zip(X[:-1], X[1:]):
    flecha([(a + AN / 2, Y1), (b - AN / 2, Y1)])

# --- 2 · Modelo y servicio ----------------------------------------------------------------------------
caja(X[4], Y2, 'Muestra de modelado', '2.000 series perecederas\nhuella SHA-256', 'proceso')
caja(X[3], Y2, 'Entrenamiento', 'GB cuantil q0,75\nvalidación temporal', 'proceso')
caja(X[2], Y2, 'MLflow', 'corridas + Model Registry\nalias @champion', 'datos')
caja(X[1], Y2, 'API FastAPI', '/predecir/lote · /deriva\nrespaldo: regla actual', 'servicio')
caja(X[0], Y2, 'Tablero Streamlit', 'desempeño, deriva,\nalertas y versiones', 'servicio')
flecha([(X[4], Y1 - AL / 2), (X[4], Y2 + AL / 2)])
flecha([(X[4] - AN / 2, Y2), (X[3] + AN / 2, Y2)])
flecha([(X[3] - AN / 2, Y2), (X[2] + AN / 2, Y2)], 'registra', (57.5, Y2 + 4.9))
flecha([(X[2] - AN / 2, Y2), (X[1] + AN / 2, Y2)], 'carga @champion', (38.5, Y2 + 4.9))

# --- 3 · Producción y bucle de reentrenamiento --------------------------------------------------------
caja(X[1], Y3, 'Predicción del lote', 'produccion_lotes\n7 solicitudes de 2.000 filas', 'proceso')
caja(X[2], Y3, 'Monitoreo', 'PSI · KS · calidad\nlatencia · pérdida', 'proceso')
caja(X[3], Y3, 'Reentrenamiento', 'challenger vs champion\nΔ ahorro > 2,78 pp', 'proceso')
caja(X[4], Y3, 'Aprobación humana', 'pausa en Kestra\naprobar o rechazar', 'humano')
caja(54.5, Y4, 'Snowflake · esquema PRODUCCION',
     'LOTES · LOTES_TARGET · PREDICCIONES · DESEMPENO · MONITOREO · ALERTAS · REENTRENAMIENTOS', 'datos',
     ancho=73, alto=AL)

flecha([(X[1], Y3 + AL / 2), (X[1], Y2 - AL / 2)], 'pedido sugerido', (X[1] + 1.0, 29.3), ha='left',
       doble=True)
flecha([(X[1] + AN / 2, Y3), (X[2] - AN / 2, Y3)])
flecha([(X[2] + AN / 2, Y3), (X[3] - AN / 2, Y3)], 'alerta', (57.5, Y3 + 1.6))
flecha([(X[3] + AN / 2, Y3), (X[4] - AN / 2, Y3)])
# Aprobado: el challenger pasa a @champion y la API lo recarga
YM = (Y2 + Y3) / 2
flecha([(X[4], Y3 + AL / 2), (X[4], YM), (X[2], YM), (X[2], Y2 - AL / 2)],
       'aprobado: pasa a @champion y la API lo recarga', (67, YM), )
# Lectura y escritura en PRODUCCION
for x in X[1:4]:
    flecha([(x, Y3 - AL / 2), (x, Y4 + AL / 2)], doble=True)
flecha([(X[4] + AN / 2 - 0.3, Y1 - AL / 2), (97.6, Y1 - AL / 2 - 1.5), (97.6, Y4), (54.5 + 73 / 2, Y4)],
       'arma los\nlotes', (97.9, 30), ha='right', punteada=True)
flecha([(54.5 - 73 / 2, Y4), (3.6, Y4), (3.6, Y2 - AL / 2)], 'lee', (4.3, 13), ha='left')
ax.text(X[0] + 1.2, 20.5, 'Interruptor /respaldo:\nla API sirve la regla\nactual en lugar\ndel modelo.',
        ha='center', va='center', fontsize=8.4, color=SUAVE, style='italic')

# --- Leyenda ------------------------------------------------------------------------------------------
etiquetas = {'proceso': 'Proceso (flujo de Kestra o script)', 'datos': 'Datos y registro de modelos',
             'servicio': 'Servicio en Docker', 'humano': 'Decisión humana'}
for x, (tipo, texto) in zip([3, 21.5, 37.5, 50.5], etiquetas.items()):
    fondo, borde = TIPOS[tipo]
    ax.add_patch(FancyBboxPatch((x, 2.0), 2.2, 1.3, boxstyle='round,pad=0,rounding_size=0.3', fc=fondo, ec=borde,
                                lw=1.1))
    ax.text(x + 2.9, 2.65, texto, va='center', fontsize=8.8, color=TINTA)
ax.text(98.6, 2.65, 'Todo corre en Docker Compose local, salvo Snowflake (nube).', ha='right', va='center',
        fontsize=8.8, color=SUAVE)

fig.savefig(sys.argv[1], dpi=200, bbox_inches='tight', pad_inches=0.15, facecolor='white')
print('guardado', sys.argv[1])
