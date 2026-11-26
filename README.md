# Proyecto final · Pedido de perecederos para Corporación Favorita

Proyecto de ciencia de datos de punta a punta (PSets 1 a 4). Cada lunes sugiere cuántas unidades pedir de cada
producto perecedero en cada tienda para la semana siguiente. Opera con monitoreo, alertas, reentrenamiento con
aprobación humana y un interruptor de respaldo.

```
CSV de Kaggle → RAW → Bronze → Silver → Gold → OBT → EDA y modelo → registro (MLflow) → API
             → simulación semanal → monitoreo y alertas → reentrenamiento con aprobación
```

**Resultado:** en 10 semanas simuladas con ventas reales que el modelo no vio, el pedido sugerido costó **22,3 % menos**
que la regla de negocio actual (media de 28 días más un stock de seguridad por familia), con 29 % menos faltantes y
la misma merma. El modelo le ganó a la regla en las 10 semanas. La excepción es la familia de comida preparada, donde
quedó peor que la regla. El detalle está en `notebooks/06_simulacion_produccion.ipynb` y
`notebooks/07_analisis_monitoreo.ipynb`.

## Contenido

1. [Requisitos](#1-requisitos)
2. [Configuración: variables de entorno y Snowflake](#2-configuración-variables-de-entorno-y-snowflake)
3. [Levantar la infraestructura](#3-levantar-la-infraestructura)
4. [Orden de ejecución completo](#4-orden-de-ejecución-completo)
5. [Pruebas, CI y CD](#5-pruebas-ci-y-cd)
6. [Estructura del repositorio](#6-estructura-del-repositorio)
7. [Uso de IA](#7-uso-de-ia)

## 1. Requisitos

- **Docker Desktop** con contenedores Linux. El proyecto se probó en un equipo con 12 GB de RAM; los límites de
  memoria de cada servicio están en `docker-compose.yml`. Kestra tiene un límite de 4 GB.
- **Python 3.12**, con [uv](https://docs.astral.sh/uv/) o pip.
- **Una cuenta de Snowflake** con permiso para crear un rol, un warehouse y una base de datos. Basta una cuenta de
  prueba.
- **Los seis CSV de Corporación Favorita** de [Kaggle](https://www.kaggle.com/competitions/favorita-grocery-sales-forecasting/data):
  `train.csv`, `items.csv`, `stores.csv`, `oil.csv`, `transactions.csv` y `holidays_events.csv`. No se distribuyen en
  el repositorio. Se descomprimen en la raíz del proyecto o en la carpeta indicada por `DATA_DIR`. Hace falta espacio
  para `train.csv` (unos 5 GB) y para las imágenes de Docker.

Todos los comandos se ejecutan desde la raíz de `proyecto_final/`, en PowerShell.

Entorno de Python, para los scripts, los notebooks y las pruebas:

```powershell
uv venv --python 3.12 .venv
uv pip install -r requirements.txt --python .venv\Scripts\python.exe --index-strategy unsafe-best-match
# Kernel de Jupyter con el nombre que usan los notebooks
.venv\Scripts\python.exe -m ipykernel install --user --name pset3 --display-name "Python 3.12 (pset3 .venv)"
```

Con pip: `python -m pip install -r requirements.txt`. El archivo incluye el índice de PyTorch para CPU, que necesita
Chronos (notebooks 03 a 05).

## 2. Configuración: variables de entorno y Snowflake

```powershell
Copy-Item .env.example .env
```

| Variable | Qué poner |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Identificador `organización-cuenta`. En Snowflake: `SELECT CURRENT_ORGANIZATION_NAME() \|\| '-' \|\| CURRENT_ACCOUNT_NAME();` |
| `SNOWFLAKE_USER` | Nombre de inicio de sesión (*login name*): `DESC USER <usuario>;`, propiedad `LOGIN_NAME` |
| `SNOWFLAKE_ROLE`, `_WAREHOUSE`, `_DATABASE`, `_SCHEMA`, `_OBT_TABLE` | Los valores del ejemplo (los crea `snowflake/01_preparar_entorno.sql`) |
| `SNOWFLAKE_PRIVATE_KEY_FILE`, `_PASSPHRASE_FILE` | Los valores del ejemplo: la clave y su frase quedan en `.secrets/` |
| `DATA_DIR` | Carpeta de los seis CSV; `.` si están en la raíz. En Windows, con `/` |
| `POSTGRES_PASSWORD`, `KESTRA_PASSWORD`, `MLFLOW_POSTGRES_PASSWORD` | Contraseñas locales nuevas, a elección |
| `KESTRA_USERNAME` | Un correo cualquiera; es el usuario de la interfaz de Kestra |
| `MLFLOW_TRACKING_URI` | `http://127.0.0.1:5050` (desde el equipo; los contenedores usan `http://mlflow:5000`) |
| `API_TOKEN_ADMIN` | Un token propio y largo, por ejemplo `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `API_TAG` | El hash del commit de la imagen publicada por `cd.yml` en GHCR (§5). Vacío: la imagen de la API se construye localmente |
| `MODO_RESPALDO` | `false`. Con `true` la API arranca respondiendo con la regla de negocio |

**Conexión a Snowflake (una sola vez).** La autenticación es por par de claves RSA, sin contraseña:

1. Generar la clave: `.venv\Scripts\python.exe snowflake/02_generar_claves.py`. No sobrescribe una clave existente.
2. En una Worksheet de Snowflake, como ACCOUNTADMIN, ejecutar `snowflake/01_preparar_entorno.sql`. Crea
   `PSET2_ROLE`, `PSET2_WH` y `PSET2_DB`; el pipeline usa solo `PSET2_ROLE`.
3. Con el usuario de `SNOWFLAKE_USER`, ejecutar `.secrets/registrar_clave_publica.sql` (lo generó el paso 1). Si
   `DESCRIBE USER` muestra que `RSA_PUBLIC_KEY_FP` ya tiene un valor, usar `RSA_PUBLIC_KEY_2` en la última línea para no
   reemplazar la clave existente.
4. Guardar la frase y probar:

```powershell
.venv\Scripts\python.exe snowflake/11_configurar_secreto_local.py
.venv\Scripts\python.exe snowflake/03_probar_conexion.py
```

`.env` y `.secrets/` están en `.gitignore`: el repositorio no contiene contraseñas, claves ni tokens. Docker monta la
clave y la frase como *secrets* (`/run/secrets/...`), no como variables de entorno.

## 3. Levantar la infraestructura

Un solo comando levanta todo:

```powershell
docker compose up -d
docker compose ps        # postgres, mlflow-db, mlflow y api deben quedar "healthy"
```

| Servicio | Dirección | Para qué |
|---|---|---|
| Kestra | http://localhost:8080 | Orquestación: ingesta, lotes, monitoreo, reentrenamiento |
| Spark | http://localhost:8082 | Master de Spark. La OBT se construye con `spark-submit --master local[2]` dentro de Kestra |
| MLflow | http://localhost:5050 | Tracking y Model Registry (alias `champion` y `challenger`) |
| API | http://localhost:8000/docs | Servicio de predicción (FastAPI) |
| Tablero | http://localhost:8501 | Monitoreo lote por lote (Streamlit) |

La primera vez descarga las imágenes y construye la de Kestra, que incluye dbt, Spark 3.5.3 y los entornos de Python.
Tarda varios minutos y requiere conexión a Internet.

Para apagar sin perder datos: `docker compose down` **sin** `-v`. Con `-v` se borran los volúmenes con el historial de
Kestra, el registro de MLflow y el registro de predicciones de la API.

**Cargar los flujos en Kestra.** Los YAML del repositorio no se cargan solos. Este script los crea o los actualiza
por la API de Kestra; Kestra guarda la revisión anterior:

```powershell
.venv\Scripts\python.exe kestra/desplegar_flujos.py --con-pset2
```

## 4. Orden de ejecución completo

### 4.1 Fuente → RAW → Bronze → Silver → Gold → OBT

En Kestra: **Flows → pset2 → pipeline_completo → Execute** (unos 18 minutos). El flujo está en `kestra/ingesta.yml`;
conserva el id y el namespace del PSet 2 para no perder su historial de ejecuciones.

| Etapa | Qué hace | Archivo |
|---|---|---|
| `ingesta_raw` | Carga los seis CSV en `PSET2_DB.RAW`, con hasta 3 intentos por tarea | `kestra/pset2/02_ingesta_raw.yml`, `snowflake/04` a `09` |
| `construir_y_probar_dbt` | `dbt build`: 20 modelos Bronze, Silver y Gold y 208 pruebas | `dbt/`, `snowflake/12_ejecutar_dbt.py` |
| `construir_obt_spark` | Une las seis tablas Gold en `ANALYTICS.OBT_SALES` (13.017.002 filas fecha–tienda–producto) y la publica solo si coincide con Gold | `kestra/pset2/18_spark_obt.yml`, `spark/02_construir_obt.py` |

Si una etapa falla, las siguientes no corren. El flujo tiene un **trigger diario a las 06:00** (hora de Ecuador) que lo
ejecuta sin intervención. Verificación final: `snowflake/26_verificar_obt.sql` en Snowsight.

**Reintentos y backfill.** `pset2.probar_reintentos` falla a propósito en el intento 1 y se recupera en el 2, sin tocar
datos. `pset2.backfill_ventas` repone solo un intervalo de fechas de `RAW.TRAIN` y comprueba que el resto de la tabla no
cambió. No debe correr al mismo tiempo que `ingesta_raw`. Para guardar la evidencia de cualquier ejecución (estado,
intentos y logs, con la cuenta de Snowflake oculta):

```powershell
.venv\Scripts\python.exe kestra/evidencia.py <id_de_la_ejecucion>     # → docs/evidencias/
```

### 4.2 EDA y modelo

Con MLflow levantado, se extrae la muestra de modelado y se ejecutan los notebooks en orden, cada uno con **Restart**
y **Run All**:

```powershell
.venv\Scripts\python.exe -m src.datos      # 2.000 series de la OBT → data/obt_muestra.parquet, con su SHA-256
```

| Notebook | Etapa | Tiempo aproximado |
|---|---|---|
| `01_eda.ipynb` | Exploración de la OBT y hallazgos | 1 min |
| `02_features.ipynb` | Features derivadas y prueba de no fuga | 1 min |
| `03_baseline_candidatos.ipynb` | Líneas base y 5 familias de candidatos | 2 h |
| `04_tuning.ipynb` | Optuna sobre los 3 mejores (90 corridas) | 8 h |
| `05_seleccion.ipynb` | Selección por costo de negocio, prueba y Model Registry | 1,3 h |
| `05b_reproducir_champion.ipynb` | Carga la versión 1 del registro (champion del PSet 3) y reproduce exactamente su RMSLE y su costo de prueba | 1 min |
| `06_simulacion_produccion.ipynb` | Después de la simulación (§4.5): lotes, resultado de negocio lote por lote, efecto de los reentrenamientos, independencia y trazabilidad | 3 min |
| `07_analisis_monitoreo.ipynb` | Después de la simulación (§4.6): métricas de sistema, modelo y datos, deriva, alertas, reentrenamientos y ética | 2 min |

Los notebooks 03 a 05b son los del PSet 3 y no hace falta repetirlos para operar el sistema: sus corridas ya están en
MLflow (`docs/corridas.csv`).

### 4.3 Registro del modelo de producción

El modelo de producción es el **GB-cuantil 0,75** con los hiperparámetros del PSet 3, entrenado hasta el 28/05/2017
para dejar 10 semanas de datos nuevos para la simulación (el porqué está en `docs/cambios.md`, §4):

```powershell
docker compose exec -T -w /workspace kestra /opt/proyecto-venv/bin/python -m src.reentrenar inicial
docker compose exec -T -w /workspace kestra /opt/proyecto-venv/bin/python -m src.reentrenar referencia_cv
```

`inicial` registra la versión con el alias `champion` y escribe en `api/` el contrato de entrada, la regla de respaldo
y la referencia de deriva. `referencia_cv` guarda en `monitoreo/referencia_cv.json` la media y la desviación de la
validación cruzada, de donde salen los umbrales de desempeño y de promoción. Los comandos corren dentro del contenedor
de Kestra, que ya tiene la conexión a Snowflake y a MLflow.

### 4.4 API

La API carga el modelo con alias `champion` desde MLflow, valida cada entrada contra `api/contrato.json` y registra
cada predicción con la versión del modelo y su `run_id`. La imagen la publica `cd.yml` en GHCR; con `API_TAG` en
`.env`, `docker compose up -d` la descarga. Sin `API_TAG`, se construye localmente.

| Ruta | Qué hace |
|---|---|
| `GET /salud` | Estado, versión cargada y si el interruptor de respaldo está activo |
| `GET /modelo` | Nombre, versión, alias y `run_id` del modelo que responde |
| `POST /predecir` | Pedido sugerido de un producto y un día. Una entrada inválida responde 422, con el campo y el motivo |
| `POST /predecir/lote` | Lo mismo para un lote de filas (lo usa la simulación) |
| `POST /respaldo` | Interruptor de respaldo, con token de administrador (`x-token-admin`) |
| `POST /modelo/recargar` | Vuelve a leer el alias en el acto, con token (la API también lo revisa cada 30 s) |

**Rollback:** en MLflow, mover el alias `champion` a la versión anterior y llamar a `POST /modelo/recargar`. No hay que
reconstruir ni volver a desplegar la imagen.

### 4.5 Simulación de producción

```powershell
docker compose exec -T -w /workspace kestra /opt/proyecto-venv/bin/python -m src.lotes tablas      # esquema PRODUCCION
docker compose exec -T -w /workspace kestra /opt/proyecto-venv/bin/python -m src.lotes construir   # 10 lotes semanales
```

Arma 10 lotes semanales (05/06–13/08/2017) de las 2.000 series, con dos alteraciones inducidas: en el lote 3, la fuente
de transacciones a la mitad más 3 filas defectuosas, y desde el lote 5, la demanda multiplicada por 1,5 (`src/lotes.py`).

Después, en Kestra: **Flows → proyecto_final → simulacion → Execute** (pasos 1 a 12). Cada paso corre:

1. `produccion_lotes`: manda el lote a la API y evalúa los lotes cuyo target ya llegó.
2. `monitoreo`: métricas, alertas y diagnóstico.
3. `reentrenamiento`, si el monitoreo lo pide.

Para repetir la simulación desde cero: `python -m src.produccion reiniciar` (mismo `docker compose exec`).

### 4.6 Monitoreo

El flujo `monitoreo` guarda una fila por lote en `PRODUCCION.MONITOREO` y las alertas en `PRODUCCION.ALERTAS`. Las
alertas también aparecen en el log de Kestra con nivel WARN.

| Tipo | Métricas |
|---|---|
| Sistema | Latencia p50 y p95, errores 4xx y 5xx, volumen de peticiones |
| Modelo | Distribución de los pedidos, tasa de cada decisión, pérdida y costo cuando llega el target |
| Datos | Faltantes, valores fuera de rango, categorías no vistas, PSI por feature, KS y chi-cuadrado |

El tablero (http://localhost:8501) muestra todo lote por lote, con las alertas y los reentrenamientos marcados. Los
análisis están en `notebooks/06_simulacion_produccion.ipynb` y `notebooks/07_analisis_monitoreo.ipynb`.

### 4.7 Reentrenamiento

`reentrenamiento` se dispara cuando la pérdida relativa supera la media de la CV más 2 desviaciones en 2 lotes
seguidos, o cada 4 lotes. También se puede lanzar a mano. Entrena un challenger y lo compara con el champion en el
último lote con target. Después se detiene en una **pausa de aprobación**: en la página de la ejecución, **Resume**, con
`aprobar` y `motivo_decision`. No hay que usar *Restart* ni *Change state*, porque reanudan sin formulario y se toma
como rechazo. Si se aprueba, el alias `champion` pasa al challenger y la API lo carga.

### 4.8 Exportar los resultados

```powershell
docker compose exec -T -w /workspace kestra /opt/proyecto-venv/bin/python -m src.exportar
```

Escribe en `docs/` los archivos `predicciones.csv`, `monitoreo.csv`, `alertas.csv`, `corridas.csv` (todas las
corridas, con `mlflow.search_runs`), `reentrenamientos.csv` y `solicitudes.csv`.

## 5. Pruebas, CI y CD

```powershell
uv pip install -r tests/requirements.txt --python .venv\Scripts\python.exe
.venv\Scripts\python.exe -m pytest -q
```

| Archivo | Qué cubre |
|---|---|
| `tests/test_contrato.py` | La API responde con pedido, decisión y versión; rechaza con 422 tipos incorrectos, categorías desconocidas, valores fuera de rango y el target; el esquema coincide con la firma del modelo en MLflow |
| `tests/test_modelo.py` | El modelo de `tests/fixtures/` reproduce la métrica registrada, es el cuantil 0,75 y su cobertura está cerca de ese cuantil |
| `tests/test_comportamiento.py` | Más ventas pasadas no reducen el pedido, un producto que dejó de venderse recibe menos, el fin de semana pide más que un martes y el pedido nunca es negativo |
| `tests/test_respaldo.py` | Interruptor por variable de entorno y por ruta protegida, la regla de respaldo y su registro |
| `tests/test_monitoreo.py`, `tests/test_alertas.py` | Registro de predicciones, métricas de sistema, PSI, calidad de datos, alertas, diagnóstico y disparadores del reentrenamiento |

- **CI** (`.github/workflows/ci.yml`): en cada push y pull request instala las dependencias, corre pytest y construye y
  prueba la imagen de la API con el modelo de `tests/fixtures/`.
- **CD** (`.github/workflows/cd.yml`): en cada merge a `main` con las pruebas en verde, publica la imagen en GitHub
  Container Registry con el hash del commit como tag. El código se despliega solo; el modelo no: cambia únicamente
  cuando una persona aprueba un challenger.

## 6. Estructura del repositorio

| Ruta | Contenido |
|---|---|
| `docker-compose.yml` | Kestra, Spark, MLflow, la API y el tablero |
| `kestra/` | Imagen de Kestra y flujos: `ingesta.yml` (CSV a OBT, trigger diario), `produccion_lotes.yml`, `monitoreo.yml`, `reentrenamiento.yml`, `simulacion.yml`; `desplegar_flujos.py` y `evidencia.py` |
| `kestra/pset2/` | Subflujos de datos del PSet 2 que llama `ingesta.yml`: carga a RAW (`02_ingesta_raw.yml`) y OBT (`18_spark_obt.yml`); además, reintentos y backfill |
| `snowflake/` | Preparación de Snowflake, claves, carga de CSV, ejecución de dbt y Spark, verificación de la OBT y tablas de producción |
| `dbt/` | Modelos Bronze, Silver y Gold con sus pruebas |
| `spark/` | Construcción y validación de la OBT |
| `exploracion/` | Diagnóstico de calidad de los CSV antes de transformarlos (PSet 2) |
| `src/` | `datos.py` (Snowflake y muestra), `pipeline.py` (features, preparación y validación), `negocio.py` (costo, decisión y regla de respaldo), `reentrenar.py`, `lotes.py`, `produccion.py`, `exportar.py` |
| `notebooks/` | 01 a 05b (PSet 3), 06 y 07 (simulación y monitoreo) |
| `api/` | Servicio FastAPI (`main.py`, `esquemas.py`), contrato de entrada, regla de respaldo, referencia de deriva y Dockerfile |
| `monitoreo/` | `deriva.py` (PSI, KS, chi-cuadrado y calidad) y `alertas.py` (alertas, diagnóstico y disparadores) |
| `tablero/` | Tablero de Streamlit y su Dockerfile |
| `tests/` | Pruebas y el modelo de fixtures |
| `mlflow/` | Imagen del servidor de MLflow |
| `docs/` | CSV exportados, `cambios.md`, evidencias de Kestra, diagramas (`arquitectura.png` y `modelo_dimensional.png`, generados con `docs/diagramas/`) y entregables; `docs/historial/` guarda los entregables de los PSets 1 a 3 y las versiones corregidas |

## 7. Uso de IA

Se usó IA generativa (Claude, de Anthropic) como apoyo durante todo el proyecto:

- Guía para resolver los ejercicios y revisión de conceptos.
- Troubleshooting y depuración de código, y resolución de problemas de conexión (Snowflake, MLflow, Docker y Kestra).
- Redacción de los textos de los notebooks, del README y de los borradores de los documentos.

Las decisiones y criterios de diseño (formulación, métricas, umbrales, validación, modelo, reglas de alerta y de
promoción) y la revisión final de todos los resultados son de la autora.
