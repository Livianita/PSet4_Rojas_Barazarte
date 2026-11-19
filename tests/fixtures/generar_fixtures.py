"""Genera los fixtures de las pruebas a partir del champion registrado en MLflow.

    python tests/fixtures/generar_fixtures.py

1. Exporta el champion con mlflow.sklearn.save_model a tests/fixtures/modelo/
   (en CI no hay servidor de MLflow).
2. Guarda una muestra fija de 3.000 filas (semilla 42) de los últimos 16 días antes
   del corte del entrenamiento, con su target real, en muestra_fija.parquet.
3. Calcula la pérdida cuantil del champion en esa muestra, la registra en la
   corrida de MLflow (perdida_cuantil_muestra_fija) y copia el valor registrado a
   metrica_registrada.json. test_modelo.py comprueba que el modelo exportado la
   reproduce.

La muestra está dentro del entrenamiento: la prueba verifica que el artefacto, la
preparación y las versiones de las librerías reproducen el número registrado, no
la capacidad de generalizar (eso lo mide la CV y, en producción, el monitoreo).
"""

import json
import os
import shutil
import sys
import warnings
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault('MLFLOW_ALLOW_MODEL_CODE_EXECUTION', 'true')
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')
warnings.filterwarnings('ignore')

import mlflow  # noqa: E402
import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402
from sklearn.metrics import mean_pinball_loss  # noqa: E402

from src.datos import cargar_muestra  # noqa: E402
from src.negocio import CUANTIL  # noqa: E402
from src.pipeline import HORIZONTE, OBJETIVO, construir_features  # noqa: E402
from src.reentrenar import COLUMNAS_X, CONFIABLES, MODELO_REGISTRADO  # noqa: E402

DESTINO = Path(__file__).parent
N_MUESTRA, SEMILLA = 3000, 42

load_dotenv(RAIZ / '.env')
cliente = MlflowClient()
version = cliente.get_model_version_by_alias(MODELO_REGISTRADO, 'champion')
corrida = cliente.get_run(version.run_id)
fin = pd.Timestamp(corrida.data.params['fin_entrenamiento'])
modelo = mlflow.sklearn.load_model(f'models:/{MODELO_REGISTRADO}/{version.version}')

datos = construir_features(cargar_muestra()[0])
ventana = datos[pd.to_datetime(datos['DATE']).between(fin - pd.Timedelta(days=HORIZONTE - 1), fin)]
muestra = ventana.sample(N_MUESTRA, random_state=SEMILLA).sort_values(['DATE', 'STORE_NBR', 'ITEM_NBR'])
muestra = muestra[COLUMNAS_X + [OBJETIVO]].reset_index(drop=True)
muestra.to_parquet(DESTINO / 'muestra_fija.parquet', index=False)

metrica = mean_pinball_loss(muestra[OBJETIVO], modelo.predict(muestra[COLUMNAS_X]).clip(0), alpha=CUANTIL)
mlflow.log_metric('perdida_cuantil_muestra_fija', metrica, run_id=version.run_id)
registrada = cliente.get_run(version.run_id).data.metrics['perdida_cuantil_muestra_fija']

carpeta = DESTINO / 'modelo'
if carpeta.exists():
    shutil.rmtree(carpeta)
mlflow.sklearn.save_model(modelo, carpeta, serialization_format='skops', skops_trusted_types=CONFIABLES,
                          signature=mlflow.models.get_model_info(
                              f'models:/{MODELO_REGISTRADO}/{version.version}').signature,
                          pip_requirements=str(RAIZ / 'api' / 'requirements.txt'))
(DESTINO / 'metrica_registrada.json').write_text(json.dumps({
    'modelo': MODELO_REGISTRADO, 'version': version.version, 'run_id': version.run_id,
    'metrica': 'perdida_cuantil_muestra_fija', 'valor': registrada, 'cuantil': CUANTIL,
    'filas': N_MUESTRA, 'semilla': SEMILLA, 'ventana': [str((fin - pd.Timedelta(days=HORIZONTE - 1)).date()),
                                                        str(fin.date())]}, indent=2), encoding='utf-8')
print(f'versión {version.version} · {N_MUESTRA} filas · pérdida cuantil registrada {registrada:.6f}')
print('tamaño del modelo exportado:', sum(f.stat().st_size for f in carpeta.rglob('*')) // 1024, 'KB')
