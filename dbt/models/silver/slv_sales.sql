-- Misma observación que Bronze. No borrar devoluciones ni crear días ausentes.
select
    id, date, store_nbr, item_nbr,
    unit_sales as unit_sales_original,
    unit_sales_original as unit_sales_source_text,
    unit_sales < 0 as is_return,
    greatest(unit_sales, 0) as unit_sales_target,
    onpromotion,
    source_file, source_row_number, load_batch_id, loaded_at, source_sha256
from {{ ref('brz_sales') }}
