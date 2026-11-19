-- Una prueba dbt falla si esta consulta devuelve filas.
-- Comparamos con Raw, no con una constante que podría cambiar con la fuente.
select origen.filas as filas_raw, bronze.filas as filas_bronze
from (select count(*) as filas from {{ source('favorita_raw', 'items') }}) origen
cross join (select count(*) as filas from {{ ref('brz_items') }}) bronze
where origen.filas <> bronze.filas
