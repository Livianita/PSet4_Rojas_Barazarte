-- Reconciliación decimal: no convertir devoluciones a cero ni perder filas.
with origen as (
    select count(*) as filas,
           count_if(try_to_decimal(unit_sales, 18, 6) < 0) as negativos,
           sum(try_to_decimal(unit_sales, 18, 6)) as total_ventas
    from {{ source('favorita_raw', 'train') }}
), bronze as (
    select count(*) as filas,
           count_if(unit_sales < 0) as negativos,
           sum(unit_sales) as total_ventas
    from {{ ref('brz_sales') }}
)
select origen.filas as filas_raw, bronze.filas as filas_bronze,
       origen.negativos as negativos_raw, bronze.negativos as negativos_bronze,
       origen.total_ventas as ventas_raw, bronze.total_ventas as ventas_bronze
from origen cross join bronze
where origen.filas is distinct from bronze.filas
   or origen.negativos is distinct from bronze.negativos
   or origen.total_ventas is distinct from bronze.total_ventas
