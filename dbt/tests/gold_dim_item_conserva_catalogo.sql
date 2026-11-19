select s.item_nbr as producto_silver, d.item_nbr as producto_gold
from {{ ref('slv_items') }} s
full outer join {{ ref('dim_item') }} d on s.item_nbr = d.item_nbr
where s.item_nbr is null or d.item_nbr is null
   or (d.item_key is distinct from s.item_nbr)
   or (s.family is distinct from d.family)
   or (s.item_class is distinct from d.item_class)
   or (s.perishable is distinct from d.perishable)
   or (s.source_file is distinct from d.source_file)
   or (s.source_row_number is distinct from d.source_row_number)
   or (s.load_batch_id is distinct from d.load_batch_id)
   or (s.loaded_at is distinct from d.loaded_at)
