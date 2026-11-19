-- Tipar no debe eliminar ni multiplicar observaciones.
select origen.filas as filas_raw, bronze.filas as filas_bronze
from (select count(*) as filas from {{ source('favorita_raw', 'transactions') }}) origen
cross join (select count(*) as filas from {{ ref('brz_transactions') }}) bronze
where origen.filas <> bronze.filas
