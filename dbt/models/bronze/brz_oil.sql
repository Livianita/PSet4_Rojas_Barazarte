-- Una fila por fecha presente en el CSV; aún no se completa el calendario.
with origen as (
    select * from {{ source('favorita_raw', 'oil') }}
), tipado as (
    select
        try_to_date(nullif(trim(date), ''), 'YYYY-MM-DD') as date,
        try_to_decimal(nullif(trim(dcoilwtico), ''), 18, 6) as dcoilwtico,
        date as date_original,
        dcoilwtico as dcoilwtico_original,
        source_file, source_row_number, load_batch_id, loaded_at
    from origen
)
select *,
    date is null as has_invalid_date,
    nullif(trim(dcoilwtico_original), '') is null as is_price_missing,
    (
        nullif(trim(dcoilwtico_original), '') is not null
        and dcoilwtico is null
    ) as has_invalid_price
from tipado
