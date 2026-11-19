-- Detectar pérdida/alta de productos y cambios en atributos o trazabilidad.
select b.item_nbr as producto_bronze, s.item_nbr as producto_silver
from {{ ref('brz_items') }} b
full outer join {{ ref('slv_items') }} s on b.item_nbr = s.item_nbr
where b.item_nbr is null or s.item_nbr is null
   or (b.family is distinct from s.family)
   or (b.item_class is distinct from s.item_class)
   or (b.perishable is distinct from s.perishable)
   or (b.source_file is distinct from s.source_file)
   or (b.source_row_number is distinct from s.source_row_number)
   or (b.load_batch_id is distinct from s.load_batch_id)
   or (b.loaded_at is distinct from s.loaded_at)
