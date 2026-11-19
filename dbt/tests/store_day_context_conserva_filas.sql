select e.filas as filas_eventos, c.filas as filas_contexto
from (select count(*) as filas from {{ ref('slv_store_day_events') }}) e
cross join (select count(*) as filas from {{ ref('slv_store_day_context') }}) c
where e.filas <> c.filas
