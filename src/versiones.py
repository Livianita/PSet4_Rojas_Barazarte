"""Lista las versiones registradas de favorita-perecederos-modelo, con la corrida de
cada una, su fase, su corte de entrenamiento, su métrica y sus alias.

    python -m src.versiones
"""

import logging

from dotenv import load_dotenv
from mlflow import MlflowClient

from src.reentrenar import MODELO_REGISTRADO, RAIZ

logging.getLogger('mlflow').setLevel(logging.ERROR)

NOMBRE = MODELO_REGISTRADO

if __name__ == '__main__':
    load_dotenv(RAIZ / '.env')
    cliente = MlflowClient()
    aliases = {}
    for alias, numero in cliente.get_registered_model(NOMBRE).aliases.items():
        aliases.setdefault(numero, []).append(alias)
    for version in sorted(cliente.search_model_versions(f"name='{NOMBRE}'"), key=lambda v: int(v.version)):
        corrida = cliente.get_run(version.run_id)
        perdida = corrida.data.metrics.get('perdida_cuantil_cv', corrida.data.metrics.get('perdida_cuantil_prueba'))
        texto = f'{perdida:.4f}' if perdida is not None else '-'
        print(f"Versión {version.version}: {version.tags.get('modelo', '-')}, fase {corrida.data.tags.get('fase', '-')}, "
              f"entrenado hasta {corrida.data.params.get('fin_entrenamiento', corrida.data.params.get('fecha_corte_snapshot'))}, "
              f"pérdida cuantil {texto}, corrida {version.run_id[:12]}, alias: {', '.join(aliases.get(version.version, [])) or '-'}")
