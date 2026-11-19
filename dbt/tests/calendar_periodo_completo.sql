select count(*) as filas, min(date) as inicio, max(date) as fin
from {{ ref('slv_calendar') }}
having count(*) <> datediff('day', '2016-08-01'::date, '2017-08-15'::date) + 1
    or min(date) is distinct from '2016-08-01'::date
    or max(date) is distinct from '2017-08-15'::date
