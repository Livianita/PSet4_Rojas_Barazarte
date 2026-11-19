-- Ejecutar en una SQL Worksheet de tu cuenta de Snowflake, en este orden.
-- Este script crea recursos; no carga ventas ni configura autenticación.

-- 1. Alta inicial de permisos para nuestro rol de proyecto.
USE ROLE ACCOUNTADMIN;
-- Las comillas preservan mayúsculas/minúsculas del usuario al usar IDENTIFIER.
SET usuario_actual = (SELECT '"' || REPLACE(CURRENT_USER(), '"', '""') || '"');
CREATE ROLE IF NOT EXISTS PSET2_ROLE;
GRANT ROLE PSET2_ROLE TO USER IDENTIFIER($usuario_actual);
GRANT ROLE PSET2_ROLE TO ROLE SYSADMIN;

-- 2. Recursos del proyecto, administrados inicialmente por SYSADMIN.
USE ROLE SYSADMIN;
CREATE WAREHOUSE IF NOT EXISTS PSET2_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Cómputo para el pipeline académico PSET2';

CREATE DATABASE IF NOT EXISTS PSET2_DB;
GRANT USAGE ON WAREHOUSE PSET2_WH TO ROLE PSET2_ROLE;
GRANT USAGE, CREATE SCHEMA ON DATABASE PSET2_DB TO ROLE PSET2_ROLE;

-- 3. Trabajamos con el rol del proyecto, que será dueño de estos esquemas.
USE ROLE PSET2_ROLE;
USE WAREHOUSE PSET2_WH;
USE DATABASE PSET2_DB;
CREATE SCHEMA IF NOT EXISTS RAW;
CREATE SCHEMA IF NOT EXISTS BRONZE;
CREATE SCHEMA IF NOT EXISTS SILVER;
CREATE SCHEMA IF NOT EXISTS GOLD;
CREATE SCHEMA IF NOT EXISTS ANALYTICS;
USE SCHEMA RAW;

-- 4. Verificación. La consulta debe mostrar los recursos PSET2 seleccionados.
SELECT CURRENT_ROLE() AS rol,
       CURRENT_WAREHOUSE() AS warehouse,
       CURRENT_DATABASE() AS base_de_datos,
       CURRENT_SCHEMA() AS esquema;

SHOW SCHEMAS IN DATABASE PSET2_DB;

-- IF NOT EXISTS evita reemplazar objetos existentes, pero no corrige su
-- configuración ni su propietario si ya existían. Verificar sus propiedades.
SHOW WAREHOUSES LIKE 'PSET2_WH';
