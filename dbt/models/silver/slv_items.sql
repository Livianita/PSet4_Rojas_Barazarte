-- Catálogo de negocio completo. Bronze ya resolvió los tipos y validó formatos.
-- No forzar nuevas limpiezas ni filtrar a los 986 perecederos.
select item_nbr, family, item_class, perishable,
       source_file, source_row_number, load_batch_id, loaded_at
from {{ ref('brz_items') }}
