select c.date, c.store_nbr
from {{ ref('slv_store_day_context') }} c
left join {{ ref('brz_transactions') }} t on c.date = t.date and c.store_nbr = t.store_nbr
where (c.transactions_observed is distinct from t.transactions)
   or (c.has_transactions is distinct from (t.date is not null))
   or (c.is_transactions_missing is distinct from (t.date is null))
   or (c.transactions_source_file is distinct from t.source_file)
   or (c.transactions_source_row_number is distinct from t.source_row_number)
   or (c.transactions_load_batch_id is distinct from t.load_batch_id)
