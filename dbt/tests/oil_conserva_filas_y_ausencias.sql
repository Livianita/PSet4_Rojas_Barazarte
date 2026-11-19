-- En Bronze no deben perderse filas ni imputarse precios vacíos.
with origen as (
    select count(*) as filas,
           count_if(nullif(trim(dcoilwtico), '') is null) as precios_ausentes
    from {{ source('favorita_raw', 'oil') }}
), bronze as (
    select count(*) as filas,
           count_if(dcoilwtico is null) as precios_ausentes
    from {{ ref('brz_oil') }}
)
select origen.filas as filas_raw, bronze.filas as filas_bronze,
       origen.precios_ausentes as ausencias_raw,
       bronze.precios_ausentes as ausencias_bronze
from origen cross join bronze
where origen.filas <> bronze.filas
   or origen.precios_ausentes <> bronze.precios_ausentes
