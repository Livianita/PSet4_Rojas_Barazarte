-- La transformación debe preservar la cantidad de filas del catálogo Raw.
select origen.filas as filas_raw, bronze.filas as filas_bronze
from (select count(*) as filas from {{ source('favorita_raw', 'stores') }}) origen
cross join (select count(*) as filas from {{ ref('brz_stores') }}) bronze
where origen.filas <> bronze.filas
