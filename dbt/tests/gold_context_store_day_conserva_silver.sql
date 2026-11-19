with gold_descrito as (
    select f.*, d.date, t.store_nbr
    from {{ ref('fct_store_day_context') }} f
    left join {{ ref('dim_date') }} d on f.date_key = d.date_key
    left join {{ ref('dim_store') }} t on f.store_key = t.store_key
)
select s.date as fecha_silver, s.store_nbr as tienda_silver,
       g.date_key, g.store_key
from {{ ref('slv_store_day_context') }} s
full outer join gold_descrito g on s.date = g.date and s.store_nbr = g.store_nbr
where s.date is null or g.date_key is null
   or (s.applicable_event_count is distinct from g.applicable_event_count)
   or (s.active_holiday_count is distinct from g.active_holiday_count)
   or (s.is_holiday is distinct from g.is_holiday)
   or (s.has_transferred_holiday is distinct from g.has_transferred_holiday)
   or (s.is_transfer_day is distinct from g.is_transfer_day)
   or (s.is_additional_day is distinct from g.is_additional_day)
   or (s.is_bridge_day is distinct from g.is_bridge_day)
   or (s.is_work_day is distinct from g.is_work_day)
   or (s.has_special_event is distinct from g.has_special_event)
   or (s.event_descriptions is distinct from g.event_descriptions)
   or (s.transactions_observed is distinct from g.transactions_observed)
   or (s.has_transactions is distinct from g.has_transactions)
   or (s.is_transactions_missing is distinct from g.is_transactions_missing)
   or (s.transactions_source_file is distinct from g.transactions_source_file)
   or (s.transactions_source_row_number is distinct from g.transactions_source_row_number)
   or (s.transactions_load_batch_id is distinct from g.transactions_load_batch_id)
