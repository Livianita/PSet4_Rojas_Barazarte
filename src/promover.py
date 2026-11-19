"""Pone un alias en una versión de favorita-perecederos-modelo: la versión que el
servicio tiene que cargar.

    python -m src.promover 3                 # champion → versión 3
    python -m src.promover 4 challenger      # challenger → versión 4

Mover el alias champion a otra versión es todo lo que hace falta para cambiar de
modelo, o para volver al anterior (rollback): el servicio revisa el alias cada 30
segundos y carga la versión nueva sin reconstruir la imagen.
"""

import logging
import sys

from dotenv import load_dotenv
from mlflow import MlflowClient

from src.reentrenar import MODELO_REGISTRADO, RAIZ

logging.getLogger('mlflow').setLevel(logging.ERROR)

NOMBRE = MODELO_REGISTRADO

if __name__ == '__main__':
    load_dotenv(RAIZ / '.env')
    version = sys.argv[1]
    alias = sys.argv[2] if len(sys.argv) > 2 else 'champion'
    cliente = MlflowClient()
    anterior = cliente.get_registered_model(NOMBRE).aliases.get(alias)
    cliente.set_registered_model_alias(NOMBRE, alias, version)
    actual = cliente.get_model_version_by_alias(NOMBRE, alias)
    print(f'{NOMBRE}@{alias}: versión {anterior} → {actual.version} (corrida {actual.run_id[:12]})')
