"""Guarda en docs/evidencias/ la evidencia de una ejecución de Kestra: estado, origen (manual o
trigger), cada intento de cada tarea y los logs, sin datos de conexión.

    python kestra/evidencia.py <id_ejecucion> [<id_ejecucion> ...]

Escribe docs/evidencias/<flujo>_<id>.json. Usa la API de Kestra con el usuario y la contraseña de
.env, igual que kestra/desplegar_flujos.py.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / '.env')
URL = os.environ.get('KESTRA_URL', 'http://localhost:8080').rstrip('/') + '/api/v1/main'
AUTENTICACION = (os.environ.get('KESTRA_USERNAME', 'local@proyecto.test'), os.environ['KESTRA_PASSWORD'])
CARPETA = RAIZ / 'docs' / 'evidencias'
NIVELES = {'INFO', 'WARN', 'ERROR'}        # DEBUG y TRACE repiten comandos completos; no aportan evidencia
# Los logs de la ingesta y de Spark pueden mostrar la cuenta y el usuario de Snowflake: se ocultan.
SECRETOS = [v for v in (os.environ.get(k, '').strip() for k in
                        ('SNOWFLAKE_ACCOUNT', 'SNOWFLAKE_USER', 'KESTRA_USERNAME', 'KESTRA_PASSWORD',
                         'API_TOKEN_ADMIN', 'SNOWFLAKE_PRIVATE_KEY_PASSPHRASE')) if len(v) >= 4]


def ocultar(texto):
    for secreto in SECRETOS:
        texto = texto.replace(secreto, '***').replace(secreto.upper(), '***').replace(secreto.lower(), '***')
    return texto


def obtener(ruta):
    respuesta = requests.get(f'{URL}/{ruta}', auth=AUTENTICACION, timeout=30)
    respuesta.raise_for_status()
    return respuesta.json()


def evidencia(id_ejecucion):
    e = obtener(f'executions/{id_ejecucion}')
    logs = obtener(f'logs/{id_ejecucion}')
    resumen = {
        'ejecucion': e['id'], 'flujo': f"{e['namespace']}.{e['flowId']}", 'revision_flujo': e.get('flowRevision'),
        'estado': e['state']['current'], 'inicio_utc': e['state']['startDate'],
        'fin_utc': e['state'].get('endDate'), 'duracion': e['state'].get('duration'),
        'origen': (e.get('trigger') or {}).get('id') and {
            'trigger': e['trigger']['id'], 'tipo': e['trigger'].get('type'),
            'fecha_programada': (e['trigger'].get('variables') or {}).get('date')} or 'manual',
        'inputs': e.get('inputs'),
        'etiquetas': {l['key']: l['value'] for l in e.get('labels', [])},
        'tareas': [{'tarea': t['taskId'], 'estado': t['state']['current'],
                    'intentos': [{'intento': i + 1, 'estado': a['state']['current'],
                                  'inicio_utc': a['state']['startDate']} for i, a in enumerate(t.get('attempts') or [])]}
                   for t in e.get('taskRunList') or []],
        'logs': [{'hora_utc': l['timestamp'], 'tarea': l.get('taskId'), 'intento': (l.get('attemptNumber') or 0) + 1,
                  'nivel': l['level'], 'mensaje': l['message'][:1000]}
                 for l in logs if l['level'] in NIVELES],
    }
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA / f"{e['flowId']}_{e['id']}.json"
    ruta.write_text(ocultar(json.dumps(resumen, indent=2, ensure_ascii=False)), encoding='utf-8')
    print(f"{ruta.relative_to(RAIZ)}: {resumen['flujo']} {resumen['estado']}, origen {resumen['origen']}")


if __name__ == '__main__':
    for id_ejecucion in sys.argv[1:]:
        evidencia(id_ejecucion)
