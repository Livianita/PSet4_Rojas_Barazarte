select date, store_nbr, item_nbr, count(*) as apariciones
from {{ ref('brz_sales') }}
group by date, store_nbr, item_nbr
having count(*) > 1
