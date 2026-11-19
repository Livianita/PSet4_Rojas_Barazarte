select date, store_nbr, count(*) as apariciones
from {{ ref('slv_store_day_events') }}
group by date, store_nbr
having count(*) > 1
