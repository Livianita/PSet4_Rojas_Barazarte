# Anexo de evidencias

Complementa el [memo técnico](../PSet2_memo_Rojas_Barazarte.pdf). Todos los
archivos citados están en `docs/evidencias/`. Las horas de los archivos de
ejecución están en UTC; las de las capturas de Kestra, en hora de Ecuador
(America/Guayaquil, UTC−5).

## Índice

| Evidencia | Origen | Resultado |
|---|---|---|
| [`docs/evidencias/dbt_build_resumen.json`](dbt_build_resumen.json) | Resumen de `dbt/target/run_results.json` del `dbt build` ejecutado por `pipeline_completo` el 14/11/2026 (generated_at 2026-11-14T18:17:07Z). Solo campos de ejecución, sin datos de conexión | 20 modelos en success, incluido `fct_sales_panel`; 208 tests en pass; ningún error, fallo u omisión |
| `dbt/tests/gold_panel_conserva_ventas.sql`, reforzado el 15/11/2026 | Pasó de comparar conteo y suma a conciliar fila a fila, por ID, las ventas observadas del panel con `FCT_SALES` (claves, cantidades, promoción, devolución y procedencia). Ejecutado con `dbt test --select fct_sales_panel` | 17 tests del panel en pass, incluido el reforzado; el total del proyecto sigue en 208 |
| [`docs/evidencias/spark_completo_extracto.log`](spark_completo_extracto.log) | Líneas del script en el log de Kestra del subflujo `spark_obt`, ejecución `5B1z4iaKRDD1plWxV6NPWZ` (parte de `pipeline_completo` del 14/11/2026) | Seis tablas Gold leídas con claves comprobadas; 13.017.002 filas (9.933.285 observadas y 3.083.717 ceros reconstruidos); OBT publicada tras la comparación MINUS sin diferencias |
| [`docs/evidencias/verificaciones.json`](verificaciones.json) | Consultas de verificación por capa y resultados de las pruebas de reintento y backfill del 12/11/2026 | Conteos de Gold, intento 2 correcto, backfill de 55.247 filas |
| [`docs/evidencias/capturas/`](capturas/) | Capturas de la interfaz de Kestra (detalle abajo) | `pipeline_completo` en SUCCESS, reintento y backfill |
| [`snowflake/26_verificar_obt.sql`](../../snowflake/26_verificar_obt.sql) | Consulta de verificación final | Vuelve a calcular los controles de la OBT sobre las tablas vigentes |

## Panel con ceros reconstruidos (14/11/2026)

Controles de `GOLD.FCT_SALES_PANEL` y `ANALYTICS.OBT_SALES`, obtenidos con
`snowflake/26_verificar_obt.sql`:

| Control | Valor |
|---|---:|
| Filas / claves fecha–tienda–producto distintas | 13.017.002 / 13.017.002 |
| Ventas observadas = IDs distintos | 9.933.285 |
| Ceros reconstruidos: internos / posteriores a la última venta | 2.452.142 / 631.575 |
| Series con días posteriores a la última venta | 11.033 de 37.871 |
| Media del objetivo: panel completo / solo ventas observadas | 8,124 / 10,646 |
| Días-tienda con transacciones sin ventas / con ventas sin transacciones | 0 / 2 |
| Ventas observadas con promoción NULL | 0 |

## Orquestación: capturas de Kestra

| Captura | Ejecución | Qué demuestra |
|---|---|---|
| [`capturas/gantt_pipeline_completo.png`](capturas/gantt_pipeline_completo.png) | `pipeline_completo` `4DJy6pi6FB7PD1WgighRq6`, 14/11/2026 13:12–13:27 | Las tres etapas en secuencia y en SUCCESS: `ingesta_raw` → `dbt build` → Spark (14 min 41 s) |
| [`capturas/topology_pipeline_completo.png`](capturas/topology_pipeline_completo.png) | Misma ejecución | Dependencias entre subflujos: ingesta 3 min 1 s, dbt 1 min 11 s, Spark 10 min 27 s; rama `registrar_fallo` sin ejecutar; trigger diario definido |
| [`capturas/reintento_logs.png`](capturas/reintento_logs.png) | `probar_reintentos` `5qQ4H2w14rJSjql5xwWDnt`, 12/11/2026 | El intento 1 falla (exit code 1) y el intento 2 se recupera sin intervención |
| [`capturas/reintento_gantt.png`](capturas/reintento_gantt.png) | `probar_reintentos` `7cZPg8v7U6CnNq4CblKyht`, 14/11/2026 | Repetición de la prueba: la tarea termina en SUCCESS en el intento 2 |
| [`capturas/backfill_overview.png`](capturas/backfill_overview.png) | `backfill_ventas` `4EK7Jblty478fPCh0uYfgH`, 12/11/2026 | Ejecución con parámetros (`fecha_inicio` y `fecha_fin`) en SUCCESS |
| [`capturas/backfill_log_extraer_intervalo.png`](capturas/backfill_log_extraer_intervalo.png) | Misma ejecución | Extracción de 55.247 filas, del 2017-08-01 al 2017-08-02 |
| [`capturas/backfill_log_cargar_intervalo.png`](capturas/backfill_log_cargar_intervalo.png) | Misma ejecución | Carga de 55.247 filas en `RAW.TRAIN`; conteo y hash de las filas fuera del intervalo sin cambios, es decir, sin duplicados |

Mecanismos que demuestran estas ejecuciones:

- **Reintentos:** cada tarea de la ingesta admite hasta 3 intentos, por lo que un
  fallo transitorio se recupera sin intervención manual.
- **Backfill:** repone solo el intervalo pedido y, antes de confirmar la carga,
  verifica que el resto de la tabla no cambió.
- **Publicación de la OBT:** la comparación MINUS se ejecuta antes de cada
  publicación; si encuentra diferencias, Spark no publica y el log registra el error.
- **Trigger:** el disparador diario está definido y desactivado, porque las
  fuentes son históricas y estáticas.

## Líneas ERROR en el log de Spark

Kestra clasifica como ERROR todo lo que un proceso escribe en stderr, y Spark
escribe allí su propio log. Por eso, en el log completo de `spark_obt` del
14/11/2026 aparecen como ERROR 50 mensajes `INFO` de arranque y 10 `WARN`
informativos:

- `NativeCodeLoader`: no hay librerías nativas de Hadoop y Spark usa las de Java.
- `SparkStringUtils`: el texto de un plan largo se recorta en el log.
- `RowBasedKeyValueBatch spill()`: con 1 GiB de heap, una agregación cambia de estrategia interna.
- `SparkConnectorContext`: el conector cierra sus consultas al terminar.

Ninguno es un fallo. Las validaciones del script detienen el proceso con un
código distinto de 0, y la tarea terminó en SUCCESS. Para reducir ese ruido,
`snowflake/25_ejecutar_spark.py` fija `spark.log.level=WARN`. Este ajuste es
posterior a la ejecución del 14/11/2026: en una prueba con muestra, el log
quedó en 17 líneas.
