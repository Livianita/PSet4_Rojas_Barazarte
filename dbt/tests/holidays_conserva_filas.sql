-- No eliminar eventos trasladados ni eventos distintos que comparten fecha.
select origen.filas as filas_raw, bronze.filas as filas_bronze
from (select count(*) as filas from {{ source('favorita_raw', 'holidays_events') }}) origen
cross join (select count(*) as filas from {{ ref('brz_holidays_events') }}) bronze
where origen.filas <> bronze.filas
