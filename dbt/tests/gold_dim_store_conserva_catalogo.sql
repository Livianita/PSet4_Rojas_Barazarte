select s.store_nbr as tienda_silver, d.store_nbr as tienda_gold
from {{ ref('slv_stores') }} s
full outer join {{ ref('dim_store') }} d on s.store_nbr = d.store_nbr
where s.store_nbr is null or d.store_nbr is null
   or (d.store_key is distinct from s.store_nbr)
   or (s.city is distinct from d.city)
   or (s.state is distinct from d.state)
   or (s.store_type is distinct from d.store_type)
   or (s.store_cluster is distinct from d.store_cluster)
   or (s.source_file is distinct from d.source_file)
   or (s.source_row_number is distinct from d.source_row_number)
   or (s.load_batch_id is distinct from d.load_batch_id)
   or (s.loaded_at is distinct from d.loaded_at)
