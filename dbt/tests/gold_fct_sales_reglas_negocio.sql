select f.id
from {{ ref('fct_sales') }} f
left join {{ ref('dim_date') }} d on f.date_key = d.date_key
left join {{ ref('dim_item') }} i on f.item_key = i.item_key
where d.date < '2016-08-01'::date or d.date > '2017-08-15'::date
   or (i.perishable is distinct from 1)
   or (f.unit_sales_target is distinct from greatest(f.unit_sales_original, 0))
   or (f.is_return is distinct from (f.unit_sales_original < 0))
