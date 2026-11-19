-- No generamos números de fila que puedan cambiar entre ejecuciones.
select store_nbr as store_key, store_nbr, city, state, store_type, store_cluster,
       source_file, source_row_number, load_batch_id, loaded_at
from {{ ref('slv_stores') }}
