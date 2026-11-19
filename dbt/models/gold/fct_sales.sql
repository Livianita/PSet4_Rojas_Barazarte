-- Grano: una fecha–tienda–producto observado. ID conserva el identificador fuente.
-- LEFT JOIN no oculta ventas si falta una dimensión: los tests deben detectarlo.
select s.id, d.date_key, t.store_key, i.item_key,
       s.unit_sales_original, s.unit_sales_target, s.unit_sales_source_text,
       s.is_return, s.onpromotion,
       s.source_file, s.source_row_number, s.load_batch_id, s.loaded_at, s.source_sha256
from {{ ref('slv_sales') }} s
left join {{ ref('dim_date') }} d on s.date = d.date
left join {{ ref('dim_store') }} t on s.store_nbr = t.store_nbr
left join {{ ref('dim_item') }} i on s.item_nbr = i.item_nbr
