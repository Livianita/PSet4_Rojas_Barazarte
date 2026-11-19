select e.filas as filas_eventos, c.filas * s.filas as filas_esperadas
from (select count(*) as filas from {{ ref('slv_store_day_events') }}) e
cross join (select count(*) as filas from {{ ref('slv_calendar') }}) c
cross join (select count(*) as filas from {{ ref('brz_stores') }}) s
where e.filas <> c.filas * s.filas
