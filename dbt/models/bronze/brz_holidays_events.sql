-- Una fila por evento recibido; no agregamos eventos ni aplicamos traslados aún.
with origen as (
    select * from {{ source('favorita_raw', 'holidays_events') }}
), tipado as (
    select
        try_to_date(nullif(trim(date), ''), 'YYYY-MM-DD') as date,
        nullif(trim(type), '') as event_type,
        nullif(trim(locale), '') as locale,
        nullif(trim(locale_name), '') as locale_name,
        nullif(trim(description), '') as description,
        try_to_boolean(nullif(trim(transferred), '')) as transferred,
        date as date_original,
        type as event_type_original,
        locale as locale_original,
        locale_name as locale_name_original,
        description as description_original,
        transferred as transferred_original,
        source_file, source_row_number, load_batch_id, loaded_at
    from origen
)
select *,
    date is null as has_invalid_date,
    (
        transferred is null
        or not coalesce(lower(trim(transferred_original)) in ('true', 'false'), false)
    ) as has_invalid_transferred
from tipado
