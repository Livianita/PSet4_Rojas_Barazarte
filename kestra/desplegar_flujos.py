"""Carga (o actualiza) en Kestra los flujos de la carpeta kestra/, sin pasar por la interfaz.

    python kestra/desplegar_flujos.py                 # los flujos del PSet 4 (kestra/*.yml)
    python kestra/desplegar_flujos.py --con-pset2     # también los del PSet 2 (kestra/pset2/*.yml)

Usa la API de Kestra en KESTRA_URL (por defecto http://localhost:8080) con el usuario y la
contraseña de .env (KESTRA_USERNAME y KESTRA_PASSWORD). Si el flujo ya existe, lo reemplaza
por la versión del archivo; Kestra guarda la revisión anterior.
"""

import os
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / '.env')
URL = os.environ.get('KESTRA_URL', 'http://localhost:8080').rstrip('/') + '/api/v1/main/flows'
AUTENTICACION = (os.environ.get('KESTRA_USERNAME', 'local@proyecto.test'), os.environ['KESTRA_PASSWORD'])
CABECERAS = {'Content-Type': 'application/x-yaml'}


def desplegar(ruta):
    texto = ruta.read_text(encoding='utf-8')
    flujo = yaml.safe_load(texto)
    existente = requests.get(f'{URL}/{flujo["namespace"]}/{flujo["id"]}', auth=AUTENTICACION, timeout=30)
    if existente.status_code == 200:
        respuesta = requests.put(f'{URL}/{flujo["namespace"]}/{flujo["id"]}', data=texto.encode('utf-8'),
                                 headers=CABECERAS, auth=AUTENTICACION, timeout=30)
    else:
        respuesta = requests.post(URL, data=texto.encode('utf-8'), headers=CABECERAS, auth=AUTENTICACION, timeout=30)
    if not respuesta.ok:
        raise SystemExit(f'{ruta.name}: {respuesta.status_code} {respuesta.text[:500]}')
    print(f'{flujo["namespace"]}.{flujo["id"]}: revisión {respuesta.json().get("revision")}')


if __name__ == '__main__':
    archivos = sorted((RAIZ / 'kestra').glob('*.yml'))
    if '--con-pset2' in sys.argv:
        archivos += sorted((RAIZ / 'kestra' / 'pset2').glob('*.yml'))
    for archivo in archivos:
        desplegar(archivo)
