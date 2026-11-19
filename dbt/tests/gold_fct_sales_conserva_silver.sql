-- Recuperar las claves de negocio mediante dimensiones y reconciliar por ID.
select s.id as id_silver, f.id as id_gold
from {{ ref('slv_sales') }} s
full outer join {{ ref('fct_sales') }} f on s.id = f.id
left join {{ ref('dim_date') }} d on f.date_key = d.date_key
left join {{ ref('dim_store') }} t on f.store_key = t.store_key
left join {{ ref('dim_item') }} i on f.item_key = i.item_key
where s.id is null or f.id is null
   or (s.date is distinct from d.date)
   or (s.store_nbr is distinct from t.store_nbr)
   or (s.item_nbr is distinct from i.item_nbr)
   or (s.unit_sales_original is distinct from f.unit_sales_original)
   or (s.unit_sales_target is distinct from f.unit_sales_target)
   or (s.unit_sales_source_text is distinct from f.unit_sales_source_text)
   or (s.is_return is distinct from f.is_return)
   or (s.onpromotion is distinct from f.onpromotion)
   or (s.source_file is distinct from f.source_file)
   or (s.source_row_number is distinct from f.source_row_number)
   or (s.load_batch_id is distinct from f.load_batch_id)
   or (s.loaded_at is distinct from f.loaded_at)
   or (s.source_sha256 is distinct from f.source_sha256)
