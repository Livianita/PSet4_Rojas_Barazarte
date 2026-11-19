"""Diagnóstico de fuentes pequeñas; no limpia ni modifica los originales.

Ejecutar: python exploracion/06_fuentes_complementarias.py
"""

from pathlib import Path

import pandas as pd


RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / 'exploracion' / 'resultados'
SALIDA.mkdir(parents=True, exist_ok=True)

tablas = {}
for archivo in ['oil', 'transactions', 'holidays_events']:
    tabla = pd.read_csv(RAIZ / f'{archivo}.csv')
    # errors='coerce' transforma fechas no interpretables en NaT, para contarlas.
    fechas = pd.to_datetime(tabla['date'], format='%Y-%m-%d', errors='coerce')
    print(f'\n{archivo}: {len(tabla):,} filas')
    print('Fechas inválidas o vacías:', fechas.isna().sum())
    print('Cobertura:', fechas.min(), 'a', fechas.max())
    print('Valores nulos:', tabla.isna().sum().to_dict())
    print('Filas completamente repetidas:', tabla.duplicated().sum())
    tabla['date'] = fechas
    tablas[archivo] = tabla

oil = tablas['oil']
transactions = tablas['transactions']
events = tablas['holidays_events']
stores = pd.read_csv(RAIZ / 'stores.csv')
calendario = pd.date_range('2016-08-01', '2017-08-15', freq='D')
oil_periodo = oil.loc[oil['date'].isin(calendario)]
print('\nPETRÓLEO')
print('Fechas repetidas:', oil['date'].duplicated().sum())
print('Filas del período:', len(oil_periodo))
print('Precios nulos dentro del período:', oil_periodo['dcoilwtico'].isna().sum())
print('Fechas calendario del período sin fila de petróleo:',
      len(calendario.difference(oil_periodo['date'])))

trans_periodo = transactions.loc[transactions['date'].isin(calendario)]
print('\nTRANSACCIONES')
print('Claves fecha–tienda repetidas:', transactions.duplicated(['date', 'store_nbr']).sum())
print('Filas del período:', len(trans_periodo))
print('Tiendas fuera del catálogo:', (~transactions['store_nbr'].isin(stores['store_nbr'])).sum())
print('Cantidades no positivas:', transactions['transactions'].le(0).sum())
print('Pares fecha–tienda sin fila dentro del período:', len(calendario) * len(stores) -
      len(trans_periodo[['date', 'store_nbr']].drop_duplicates()))

print('\nFERIADOS Y EVENTOS')
print('Tipos:', events['type'].value_counts().to_dict())
print('Ámbitos:', events['locale'].value_counts().to_dict())
print('Valores transferred:', events['transferred'].value_counts(dropna=False).to_dict())
events_periodo = events.loc[events['date'].isin(calendario)]
print('Eventos dentro del período:', len(events_periodo))
conteos = events_periodo.groupby('date').size()
print('Fechas del período con varios eventos:', conteos.gt(1).sum())
print('Máximo de eventos en una fecha del período:', conteos.max())
print('Locales sin ciudad correspondiente:', sorted(set(
    events.loc[events['locale'].eq('Local'), 'locale_name']
) - set(stores['city'])))
print('Regionales sin provincia correspondiente:', sorted(set(
    events.loc[events['locale'].eq('Regional'), 'locale_name']
) - set(stores['state'])))

# Guardamos las fechas con más de un evento para inspección humana.
eventos_multiples = events_periodo.loc[
    events_periodo['date'].isin(conteos.loc[conteos.gt(1)].index)
].sort_values(['date', 'locale', 'locale_name'])
eventos_multiples.to_csv(SALIDA / '06_eventos_multiples_por_fecha.csv', index=False)
print('\nEjemplos de eventos en fechas compartidas:')
print(eventos_multiples.head(10).to_string(index=False))
print('\nLas ausencias detectadas no se han rellenado ni convertido en ceros.')
