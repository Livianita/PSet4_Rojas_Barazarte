select b.store_nbr as tienda_bronze, s.store_nbr as tienda_silver
from {{ ref('brz_stores') }} b
full outer join {{ ref('slv_stores') }} s on b.store_nbr = s.store_nbr
where b.store_nbr is null or s.store_nbr is null
   or (b.city is distinct from s.city)
   or (b.state is distinct from s.state)
   or (b.store_type is distinct from s.store_type)
   or (b.store_cluster is distinct from s.store_cluster)
   or (b.source_file is distinct from s.source_file)
   or (b.source_row_number is distinct from s.source_row_number)
   or (b.load_batch_id is distinct from s.load_batch_id)
   or (b.loaded_at is distinct from s.loaded_at)
