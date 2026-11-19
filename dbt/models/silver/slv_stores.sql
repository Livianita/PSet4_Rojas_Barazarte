-- Una fila por tienda; códigos de tipo y cluster conservan su significado original.
select store_nbr, city, state, store_type, store_cluster,
       source_file, source_row_number, load_batch_id, loaded_at
from {{ ref('brz_stores') }}
