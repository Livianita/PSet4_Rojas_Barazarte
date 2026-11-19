-- El calendario fecha–tienda no demuestra apertura ni existencia de ventas.
select e.*,
       t.transactions as transactions_observed,
       t.date is not null as has_transactions,
       t.date is null as is_transactions_missing,
       t.source_file as transactions_source_file,
       t.source_row_number as transactions_source_row_number,
       t.load_batch_id as transactions_load_batch_id
from {{ ref('slv_store_day_events') }} e
left join {{ ref('brz_transactions') }} t
    on e.date = t.date and e.store_nbr = t.store_nbr
