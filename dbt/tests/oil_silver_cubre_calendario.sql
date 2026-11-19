select c.filas as dias_calendario, p.filas as filas_petroleo
from (select count(*) as filas from {{ ref('slv_calendar') }}) c
cross join (select count(*) as filas from {{ ref('slv_oil_daily') }}) p
where c.filas <> p.filas
