select date_key, store_key, item_key, count(*) as apariciones
from {{ ref('fct_sales_panel') }}
group by date_key, store_key, item_key
having count(*) > 1
