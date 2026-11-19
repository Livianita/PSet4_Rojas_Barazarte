-- source() declara la dependencia de la tabla Raw; dbt resuelve su ubicación.
with origen as (
    select * from {{ source('favorita_raw', 'items') }}
), tipado as (
    select
        try_to_number(nullif(trim(item_nbr), ''), 38, 0) as item_nbr,
        nullif(trim(family), '') as family,
        try_to_number(nullif(trim(class), ''), 38, 0) as item_class,
        try_to_number(nullif(trim(perishable), ''), 38, 0) as perishable,
        -- Conservamos también el texto, para investigar conversiones inválidas.
        item_nbr as item_nbr_original,
        class as item_class_original,
        perishable as perishable_original,
        family as family_original,
        source_file, source_row_number, load_batch_id, loaded_at
    from origen
)
select *,
    -- No redondear silenciosamente códigos fraccionarios ni aceptar texto.
    (
        not coalesce(regexp_like(trim(item_nbr_original), '[0-9]+'), false)
        or not coalesce(regexp_like(trim(item_class_original), '[0-9]+'), false)
        or not coalesce(regexp_like(trim(perishable_original), '[0-9]+'), false)
        or item_nbr is null or item_class is null or perishable is null
    ) as has_invalid_numeric
from tipado
