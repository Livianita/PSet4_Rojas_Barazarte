-- El panel debe contener exactamente las ventas observadas de fct_sales, fila a fila:
-- cada ID aparece una vez en ambos lados y conserva claves, cantidades, promoción,
-- devolución y procedencia. Los ceros reconstruidos solo agregan filas.
with panel as (
    select * from {{ ref('fct_sales_panel') }} where is_observed
),
hecho as (
    select * from {{ ref('fct_sales') }}
)
select coalesce(h.id, p.source_id) as id,
       case when p.source_id is null then 'venta ausente en el panel'
            when h.id is null then 'observación sin venta en fct_sales'
            else 'atributo distinto' end as falla
from hecho h
full outer join panel p on p.source_id = h.id
where h.id is null
   or p.source_id is null
   or p.date_key is distinct from h.date_key
   or p.store_key is distinct from h.store_key
   or p.item_key is distinct from h.item_key
   or p.unit_sales_original is distinct from h.unit_sales_original
   or p.unit_sales_target is distinct from h.unit_sales_target
   or p.unit_sales_source_text is distinct from h.unit_sales_source_text
   or p.is_return is distinct from h.is_return
   or p.onpromotion is distinct from h.onpromotion
   or p.is_onpromotion_imputed
   or p.source_file is distinct from h.source_file
   or p.source_row_number is distinct from h.source_row_number
   or p.load_batch_id is distinct from h.load_batch_id
   or p.source_sha256 is distinct from h.source_sha256
