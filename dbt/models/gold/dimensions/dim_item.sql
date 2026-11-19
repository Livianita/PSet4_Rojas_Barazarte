-- En este catálogo único y estático reutilizamos la clave natural del producto.
select item_nbr as item_key, item_nbr, family, item_class, perishable,
       source_file, source_row_number, load_batch_id, loaded_at
from {{ ref('slv_items') }}
