"""Modelo dimensional de la capa Gold (PSet 2) -> docs/modelo_dimensional.png

    python docs/diagramas/modelo_dimensional.py docs/modelo_dimensional.png
"""
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams['font.family'] = 'Arial'
TINTA, SUAVE, FLECHA = '#12364f', '#4a6272', '#0f6966'
HECHO = ('#e6f2f1', '#0f6966')
DIM = ('#e8eef5', '#1d3f5e')
APOYO = ('#f3f5f6', '#7d8f9b')

fig, ax = plt.subplots(figsize=(15, 9.6))
ax.set_xlim(0, 100)
ax.set_ylim(0, 64)
ax.axis('off')


def tabla(x, y, ancho, nombre, filas, grano, columnas, colores, alto=None):
    fondo, borde = colores
    n = len(columnas)
    alto = alto or 6.2 + 1.55 * n
    ax.add_patch(FancyBboxPatch((x - ancho / 2, y - alto / 2), ancho, alto, boxstyle='round,pad=0,rounding_size=0.6',
                                fc=fondo, ec=borde, lw=1.3, zorder=2))
    arriba = y + alto / 2
    ax.text(x, arriba - 1.6, nombre, ha='center', va='center', fontsize=12, weight='bold', color=TINTA, zorder=3)
    ax.text(x, arriba - 3.3, f'{filas} filas · grano: {grano}', ha='center', va='center', fontsize=8.8,
            color=SUAVE, zorder=3)
    ax.plot([x - ancho / 2 + 0.8, x + ancho / 2 - 0.8], [arriba - 4.5] * 2, color=borde, lw=0.7, zorder=3)
    for i, columna in enumerate(columnas):
        clave = columna.endswith('_key')
        ax.text(x - ancho / 2 + 1.4, arriba - 5.7 - 1.55 * i, columna, ha='left', va='center', fontsize=9.2,
                color=TINTA if clave else SUAVE, weight='bold' if clave else 'normal', zorder=3,
                family='Consolas')
    return y - alto / 2, arriba


def flecha(a, b, punteada=False):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle='-|>', mutation_scale=13, color=FLECHA, lw=1.4,
                                 ls='--' if punteada else '-', zorder=1, shrinkA=0, shrinkB=0))


# Hechos principales (centro)
abajo_f, arriba_f = tabla(50, 33, 30, 'FCT_SALES', '9.933.285', 'fecha – tienda – producto',
                          ['date_key', 'store_key', 'item_key', 'unit_sales_target', 'onpromotion', 'is_return',
                           'source_file · source_sha256'], HECHO)
tabla(50, 13.2, 30, 'FCT_SALES_PANEL', '13.017.002', 'fecha – tienda – producto',
      ['date_key', 'store_key', 'item_key', 'unit_sales_target (0 si no hubo venta)', 'is_observed · is_imputed_zero'],
      HECHO)
ax.text(51.2, abajo_f - 1.5, 'completa con ceros los días sin venta', ha='left', va='center', fontsize=8.6,
        color=FLECHA, style='italic')
flecha((50, abajo_f), (50, abajo_f - 3.6 + 0.6))

# Dimensiones
tabla(14, 50, 24, 'DIM_DATE', '380', 'día',
      ['date_key', 'date · year · month', 'day_of_week_iso', 'is_weekend · is_payday_proxy'], DIM)
tabla(50, 55.5, 24, 'DIM_ITEM', '4.100', 'producto',
      ['item_key', 'family · item_class', 'perishable'], DIM)
tabla(86, 50, 24, 'DIM_STORE', '54', 'tienda',
      ['store_key', 'city · state', 'store_type · store_cluster'], DIM)

# Hechos de apoyo
tabla(14, 17, 24, 'FCT_OIL_DAILY', '380', 'día',
      ['date_key', 'oil_price_prepared', 'is_imputed · price_age_days'], APOYO)
tabla(86, 17, 24, 'FCT_STORE_DAY_CONTEXT', '20.520', 'día – tienda',
      ['date_key', 'store_key', 'is_holiday · is_work_day', 'transactions_observed'], APOYO)

# Relaciones (la flecha va de la dimensión al hecho)
flecha((50, 55.5 - (6.2 + 1.55 * 3) / 2), (50, arriba_f))
flecha((26, 48), (35, 40))
flecha((74, 48), (65, 40))
flecha((14, 50 - (6.2 + 1.55 * 4) / 2), (14, 17 + (6.2 + 1.55 * 3) / 2), punteada=True)
flecha((86, 50 - (6.2 + 1.55 * 3) / 2), (86, 17 + (6.2 + 1.55 * 4) / 2), punteada=True)

# Leyenda
for x, colores, texto in [(4, HECHO, 'Hechos de ventas'), (21, DIM, 'Dimensiones'),
                          (35, APOYO, 'Hechos de apoyo (contexto)')]:
    ax.add_patch(FancyBboxPatch((x, 1.2), 2.2, 1.3, boxstyle='round,pad=0,rounding_size=0.3', fc=colores[0],
                                ec=colores[1], lw=1.1))
    ax.text(x + 2.9, 1.85, texto, va='center', fontsize=9, color=TINTA)
ax.plot([57, 61], [1.85, 1.85], color=FLECHA, lw=1.4, ls='--')
ax.text(61.8, 1.85, 'clave de un hecho de apoyo', va='center', fontsize=9, color=TINTA)
ax.text(50, 4.3, 'Spark une las seis tablas en ANALYTICS.OBT_SALES, al grano del panel.', ha='center',
        va='center', fontsize=9, color=SUAVE)

fig.savefig(sys.argv[1], dpi=200, bbox_inches='tight', pad_inches=0.15, facecolor='white')
print('guardado', sys.argv[1])
