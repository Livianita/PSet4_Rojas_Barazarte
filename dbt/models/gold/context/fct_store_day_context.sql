-- Grano propio: fecha–tienda, no fecha–tienda–producto.
select d.date_key, t.store_key,
       c.applicable_event_count, c.active_holiday_count,
       c.is_holiday, c.has_transferred_holiday, c.is_transfer_day,
       c.is_additional_day, c.is_bridge_day, c.is_work_day, c.has_special_event,
       c.event_descriptions,
       c.transactions_observed, c.has_transactions, c.is_transactions_missing,
       c.transactions_source_file, c.transactions_source_row_number, c.transactions_load_batch_id
from {{ ref('slv_store_day_context') }} c
left join {{ ref('dim_date') }} d on c.date = d.date
left join {{ ref('dim_store') }} t on c.store_nbr = t.store_nbr
