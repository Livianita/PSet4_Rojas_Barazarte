select date_key, store_key, count(*) as apariciones
from {{ ref('fct_store_day_context') }}
group by date_key, store_key
having count(*) > 1
