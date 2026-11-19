USE ROLE PSET2_ROLE;
USE WAREHOUSE PSET2_WH;

-- La OBT se construye sobre GOLD.FCT_SALES_PANEL: ventas observadas + ceros
-- reconstruidos en días con la tienda abierta.
-- Esperado: 13017002 filas y claves distintas; 9933285 observadas con ID único;
-- 3083717 ceros reconstruidos (2452142 internos y 631575 tras la última venta);
-- 986 productos; 54 tiendas; 2016-08-01 a 2017-08-15; 374 devoluciones;
-- cero objetivos negativos; cero precios preparados ausentes.
SELECT COUNT(*) AS filas,
       COUNT(DISTINCT DATE_KEY, STORE_KEY, ITEM_KEY) AS claves_distintas,
       COUNT_IF(IS_OBSERVED) AS observadas,
       COUNT(DISTINCT ID) AS ids_distintos,
       COUNT_IF(IS_IMPUTED_ZERO) AS ceros_reconstruidos,
       COUNT_IF(IS_IMPUTED_ZERO AND NOT IS_AFTER_LAST_SALE) AS ceros_internos,
       COUNT_IF(IS_AFTER_LAST_SALE) AS ceros_tras_ultima_venta,
       COUNT(DISTINCT ITEM_KEY) AS productos,
       COUNT(DISTINCT STORE_KEY) AS tiendas,
       MIN(DATE) AS primera_fecha,
       MAX(DATE) AS ultima_fecha,
       COUNT_IF(IS_RETURN) AS devoluciones,
       COUNT_IF(UNIT_SALES_TARGET < 0) AS objetivos_negativos,
       COUNT_IF(OIL_PRICE_PREPARED IS NULL) AS sin_precio_preparado
FROM PSET2_DB.ANALYTICS.OBT_SALES;

-- Efecto de los ceros: media del objetivo con y sin días sin venta.
SELECT ROUND(AVG(UNIT_SALES_TARGET), 3) AS media_panel,
       ROUND(AVG(IFF(IS_OBSERVED, UNIT_SALES_TARGET, NULL)), 3) AS media_solo_observadas
FROM PSET2_DB.ANALYTICS.OBT_SALES;

-- Las transacciones se repiten por producto. No sumar TRANSACTIONS_OBSERVED
-- desde esta OBT para calcular transacciones totales: usar Gold de tienda-día.
-- IS_OBSERVED, IS_IMPUTED_ZERO, IS_ONPROMOTION_IMPUTED e IS_AFTER_LAST_SALE son
-- marcas de auditoría: no usarlas como variables del modelo (revelan el objetivo).
