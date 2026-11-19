-- Una fila por ID; detectar filas perdidas/nuevas y cambios en valores originales.
select b.id as id_bronze, s.id as id_silver
from {{ ref('brz_sales') }} b
full outer join {{ ref('slv_sales') }} s on b.id = s.id
where b.id is null or s.id is null
   or b.date is distinct from s.date
   or b.store_nbr is distinct from s.store_nbr
   or b.item_nbr is distinct from s.item_nbr
   or b.unit_sales is distinct from s.unit_sales_original
   or b.unit_sales_original is distinct from s.unit_sales_source_text
   or b.onpromotion is distinct from s.onpromotion
   or b.source_file is distinct from s.source_file
   or b.source_row_number is distinct from s.source_row_number
   or b.load_batch_id is distinct from s.load_batch_id
   or b.loaded_at is distinct from s.loaded_at
   or b.source_sha256 is distinct from s.source_sha256
