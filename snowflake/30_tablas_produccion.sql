-- Tablas de la simulación de producción (PSet 4), en el esquema PRODUCCION de PSET2_DB.
-- Las ejecuta src/lotes.py (python -m src.lotes tablas); se pueden correr también en Snowsight.
-- LOTES y LOTES_TARGET se reemplazan: se reconstruyen completas desde el snapshot de la OBT.
-- PREDICCIONES solo se crea si no existe: guarda lo que respondió el servicio.
--
-- LOTES          lo que se sabe de cada tienda–producto–día al momento de predecir (las 31
--                columnas de la firma del modelo), con el lote y sus fechas. No trae el target.
-- LOTES_TARGET   la venta real de cada fila, con la fecha en que llega: el lunes siguiente al
--                cierre de la semana, dos lotes después de la predicción.
-- PREDICCIONES   una fila por predicción servida, con la versión del modelo que la produjo.
-- DESEMPENO      métricas técnicas y de negocio de cada lote, cuando llega su target.
-- MONITOREO      una fila por lote con las métricas de sistema, de modelo, de datos y de desempeño.
-- ALERTAS        una fila por alerta disparada.
-- REENTRENAMIENTOS  una fila por reentrenamiento: challenger, comparación, regla y decisión.
--
-- Los nombres de las features van en mayúsculas: Snowflake no distingue mayúsculas en
-- identificadores sin comillas, y src/lotes.py los vuelve a minúsculas al leer.

CREATE SCHEMA IF NOT EXISTS PRODUCCION;
USE SCHEMA PRODUCCION;

CREATE OR REPLACE TABLE LOTES (
    LOTE                    INTEGER      NOT NULL,
    FECHA_PREDICCION        DATE         NOT NULL,   -- lunes anterior a la semana del lote
    FECHA_LLEGADA_TARGET    DATE         NOT NULL,   -- lunes siguiente al cierre de la semana
    DERIVA                  VARCHAR      NOT NULL,   -- ninguna | fuente_transacciones | demanda (ver src/lotes.py)
    DEFECTO                 VARCHAR,                 -- NULL, o el defecto de una fila mal formada a propósito
    STORE_NBR               INTEGER      NOT NULL,
    ITEM_NBR                INTEGER      NOT NULL,
    DATE                    DATE         NOT NULL,
    VENTA_LAG_16            FLOAT,
    VENTA_LAG_21            FLOAT,
    VENTA_LAG_28            FLOAT,
    VENTA_LAG_35            FLOAT,
    VENTA_LAG_42            FLOAT,
    MEDIA_MISMO_DIA_4       FLOAT,
    MEDIA_7_DESDE_16        FLOAT,
    MEDIA_28_DESDE_16       FLOAT,
    STD_28_DESDE_16         FLOAT,
    FRAC_CEROS_28_DESDE_16  FLOAT,
    DIAS_SIN_VENTA_16       FLOAT,
    NIVEL_SERIE_16          FLOAT,
    TRANSACCIONES_LAG_16    FLOAT,
    DAY_OF_MONTH            INTEGER,
    APPLICABLE_EVENT_COUNT  INTEGER,
    IS_PAYDAY_PROXY         INTEGER,
    IS_MONTH_END            INTEGER,
    IS_HOLIDAY              INTEGER,
    IS_TRANSFER_DAY         INTEGER,
    IS_ADDITIONAL_DAY       INTEGER,
    IS_BRIDGE_DAY           INTEGER,
    IS_WORK_DAY             INTEGER,
    HAS_SPECIAL_EVENT       INTEGER,
    DAY_OF_WEEK_ISO         VARCHAR,
    FAMILY                  VARCHAR,
    ITEM_CLASS              VARCHAR,
    STORE_TYPE              VARCHAR,
    STORE_CLUSTER           VARCHAR,
    HUELLA_DATOS            VARCHAR      NOT NULL    -- SHA-256 del snapshot de la OBT (data/obt_muestra_meta.json)
    -- Sin clave primaria: las filas mal formadas repiten la clave de una fila real (y una
    -- clave primaria en Snowflake vuelve NOT NULL a DEFECTO). La unicidad de las filas
    -- válidas la comprueba src/lotes.py antes de subir.
);

CREATE OR REPLACE TABLE LOTES_TARGET (
    LOTE                    INTEGER      NOT NULL,
    FECHA_LLEGADA_TARGET    DATE         NOT NULL,
    STORE_NBR               INTEGER      NOT NULL,
    ITEM_NBR                INTEGER      NOT NULL,
    DATE                    DATE         NOT NULL,
    UNIT_SALES_TARGET       FLOAT        NOT NULL,
    CONSTRAINT PK_LOTES_TARGET PRIMARY KEY (STORE_NBR, ITEM_NBR, DATE)
);

CREATE TABLE IF NOT EXISTS PREDICCIONES (
    ID_PREDICCION           VARCHAR      NOT NULL,
    FECHA_HORA              TIMESTAMP_NTZ NOT NULL,  -- cuándo respondió el servicio (UTC)
    LOTE                    INTEGER      NOT NULL,
    EJECUCION               VARCHAR      NOT NULL,   -- id de la ejecución de Kestra que mandó el lote
    STORE_NBR               INTEGER      NOT NULL,
    ITEM_NBR                INTEGER      NOT NULL,
    DATE                    DATE         NOT NULL,
    ENTRADAS                VARIANT,                 -- la fila que recibió el servicio
    PEDIDO                  FLOAT        NOT NULL,   -- unidades sugeridas (cuantil 0,75)
    DECISION                VARCHAR      NOT NULL,
    VERSION_MODELO          VARCHAR,                 -- NULL si respondió la regla de respaldo
    RUN_ID                  VARCHAR,
    USO_RESPALDO            BOOLEAN      NOT NULL,
    LATENCIA_MS             FLOAT,
    MODELO                  VARCHAR,                 -- nombre del modelo registrado, o 'regla de negocio'
    ALIAS                   VARCHAR,
    MOTIVO_RESPALDO         VARCHAR,
    CONSTRAINT PK_PREDICCIONES PRIMARY KEY (ID_PREDICCION)
);

-- Desempeño de cada lote, calculado cuando llega su target (dos lotes después de predecirlo).
CREATE TABLE IF NOT EXISTS DESEMPENO (
    LOTE                        INTEGER      NOT NULL,
    EVALUADO_EN_LOTE            INTEGER      NOT NULL,   -- paso de la simulación en que llegó el target
    FECHA_EVALUACION            DATE         NOT NULL,
    EJECUCION                   VARCHAR      NOT NULL,   -- ejecución que produjo las predicciones evaluadas
    VERSION_MODELO              VARCHAR,
    FILAS                       INTEGER,
    VENTA_MEDIA                 FLOAT,
    PERDIDA_CUANTIL             FLOAT,
    PERDIDA_CUANTIL_RELATIVA    FLOAT,                   -- pérdida cuantil / venta media
    RMSLE                       FLOAT,
    COSTO                       FLOAT,                   -- Co · sobrantes + Cu · faltantes, con los pedidos servidos
    COSTO_REGLA                 FLOAT,                   -- el mismo costo con la regla de negocio (línea base)
    AHORRO_VS_REGLA_PCT         FLOAT,
    MERMA                       FLOAT,
    COBERTURA                   FLOAT,
    MERMA_REGLA                 FLOAT,
    COBERTURA_REGLA             FLOAT,
    USO_RESPALDO_PCT            FLOAT,
    CONSTRAINT PK_DESEMPENO PRIMARY KEY (LOTE)
);

-- Monitoreo: una fila por lote. Las métricas de sistema, de modelo y de datos se escriben el día
-- en que se predice el lote; las de desempeño, dos pasos después, cuando llega su target
-- (monitoreo/alertas.py, flujo kestra/monitoreo.yml).
CREATE TABLE IF NOT EXISTS MONITOREO (
    LOTE                        INTEGER      NOT NULL,
    PASO                        INTEGER      NOT NULL,   -- paso en que se predijo el lote
    FECHA_PASO                  DATE         NOT NULL,
    EJECUCION                   VARCHAR,                 -- ejecución de produccion_lotes que mandó el lote
    -- sistema (registro de solicitudes de la API)
    PETICIONES                  INTEGER,
    PRODUCTOS                   INTEGER,
    ERRORES_CLIENTE             INTEGER,
    ERRORES_SERVIDOR            INTEGER,
    TASA_ERRORES_CLIENTE        FLOAT,
    TASA_ERRORES_SERVIDOR       FLOAT,
    LATENCIA_P50_MS             FLOAT,                   -- por petición (bloque de hasta 2.000 filas)
    LATENCIA_P95_MS             FLOAT,
    -- modelo (predicciones servidas)
    VERSION_MODELO              VARCHAR,
    PEDIDO_MEDIO                FLOAT,
    PEDIDO_P50                  FLOAT,
    PEDIDO_P95                  FLOAT,
    TASA_REPONER                FLOAT,
    USO_RESPALDO_PCT            FLOAT,
    -- datos (el lote tal como lo entregó la fuente, contra el entrenamiento y el contrato)
    FILAS_LOTE                  INTEGER,
    FALTANTES_MAX               FLOAT,
    FALTANTES_OBLIGATORIOS      INTEGER,
    FUERA_DE_RANGO_TOTAL        INTEGER,
    CATEGORIAS_NO_VISTAS_TOTAL  INTEGER,
    PSI_MAX                     FLOAT,
    FEATURE_PSI_MAX             VARCHAR,
    PSI                         VARIANT,                 -- PSI por feature vigilada
    PRUEBAS                     VARIANT,                 -- KS / chi-cuadrado por feature (respaldo del PSI)
    CALIDAD                     VARIANT,                 -- faltantes, fuera de rango y no vistas por feature
    -- desempeño (cuando llega el target)
    EVALUADO_EN_PASO            INTEGER,
    PERDIDA_CUANTIL             FLOAT,
    PERDIDA_CUANTIL_RELATIVA    FLOAT,
    AHORRO_VS_REGLA_PCT         FLOAT,
    COSTO                       FLOAT,
    COSTO_REGLA                 FLOAT,
    DIAGNOSTICO                 VARCHAR,                 -- tabla de la sección 6.2
    CONSTRAINT PK_MONITOREO PRIMARY KEY (LOTE)
);

-- Registro de alertas: una fila por alerta disparada en un paso.
CREATE TABLE IF NOT EXISTS ALERTAS (
    PASO                        INTEGER      NOT NULL,
    FECHA_PASO                  DATE         NOT NULL,
    LOTE                        INTEGER      NOT NULL,   -- lote al que corresponde la métrica
    ALERTA                      VARCHAR      NOT NULL,
    METRICA                     VARCHAR,
    VALOR                       FLOAT,
    UMBRAL                      VARCHAR,
    SEVERIDAD                   VARCHAR,
    RECIBE                      VARCHAR,
    ACCION                      VARCHAR,
    REGISTRADA_EN               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Reentrenamientos: una fila por ejecución del flujo reentrenamiento.yml (src/reentrenar.py).
CREATE TABLE IF NOT EXISTS REENTRENAMIENTOS (
    PASO                                INTEGER      NOT NULL,
    FECHA_PASO                          DATE         NOT NULL,
    EJECUCION                           VARCHAR,
    MOTIVO                              VARCHAR,                 -- desempeño y/o calendario
    RUN_ID                              VARCHAR,                 -- corrida de MLflow del challenger (fase=reentrenamiento)
    VERSION_CHALLENGER                  VARCHAR,
    VERSION_CHAMPION                    VARCHAR,                 -- champion con el que se comparó
    LOTES_ENTRENAMIENTO                 VARCHAR,
    LOTE_EVALUACION                     INTEGER,                 -- lote etiquetado más reciente: ninguno lo vio
    PERDIDA_CUANTIL_CHAMPION            FLOAT,
    PERDIDA_CUANTIL_RELATIVA_CHAMPION   FLOAT,
    COSTO_CHAMPION                      FLOAT,
    AHORRO_VS_REGLA_PCT_CHAMPION        FLOAT,
    PERDIDA_CUANTIL_CHALLENGER          FLOAT,
    PERDIDA_CUANTIL_RELATIVA_CHALLENGER FLOAT,
    COSTO_CHALLENGER                    FLOAT,
    AHORRO_VS_REGLA_PCT_CHALLENGER      FLOAT,
    DIFERENCIA_AHORRO_PP                FLOAT,
    UMBRAL_PROMOCION_PP                 FLOAT,                   -- 1 desviación de la CV del ahorro vs regla
    RECOMENDACION                       VARCHAR,                 -- lo que dice la regla de promoción
    DECISION                            VARCHAR,                 -- pendiente | aprobado | rechazado (persona)
    MOTIVO_DECISION                     VARCHAR,
    VERSION_CHAMPION_FINAL              VARCHAR,
    DECIDIDO_EN                         TIMESTAMP_NTZ,
    CONSTRAINT PK_REENTRENAMIENTOS PRIMARY KEY (PASO)
);
