-- Una fila por fecha y tienda observadas en transactions.csv.
with origen as (
    select * from {{ source('favorita_raw', 'transactions') }}
), tipado as (
    select
        try_to_date(nullif(trim(date), ''), 'YYYY-MM-DD') as date,
        try_to_number(nullif(trim(store_nbr), ''), 38, 0) as store_nbr,
        try_to_number(nullif(trim(transactions), ''), 38, 0) as transactions,
        date as date_original,
        store_nbr as store_nbr_original,
        transactions as transactions_original,
        source_file, source_row_number, load_batch_id, loaded_at
    from origen
)
select *,
    date is null as has_invalid_date,
    (
        not coalesce(regexp_like(trim(store_nbr_original), '[0-9]+'), false)
        or not coalesce(regexp_like(trim(transactions_original), '[0-9]+'), false)
        or store_nbr is null or transactions is null
    ) as has_invalid_numeric
from tipado
