-- Grano: una fecha, tienda y producto observados. Sin imputación ni eliminación.
with origen as (
    select * from {{ source('favorita_raw', 'train') }}
), tipado as (
    select
        try_to_number(nullif(trim(id), ''), 38, 0) as id,
        try_to_date(nullif(trim(date), ''), 'YYYY-MM-DD') as date,
        try_to_number(nullif(trim(store_nbr), ''), 38, 0) as store_nbr,
        try_to_number(nullif(trim(item_nbr), ''), 38, 0) as item_nbr,
        try_to_decimal(nullif(trim(unit_sales), ''), 18, 6) as unit_sales,
        try_to_boolean(nullif(trim(onpromotion), '')) as onpromotion,
        id as id_original,
        date as date_original,
        store_nbr as store_nbr_original,
        item_nbr as item_nbr_original,
        unit_sales as unit_sales_original,
        onpromotion as onpromotion_original,
        source_file, source_row_number, load_batch_id, loaded_at, source_sha256
    from origen
)
select *,
    date is null as has_invalid_date,
    (
        not coalesce(regexp_like(trim(id_original), '[0-9]+'), false)
        or not coalesce(regexp_like(trim(store_nbr_original), '[0-9]+'), false)
        or not coalesce(regexp_like(trim(item_nbr_original), '[0-9]+'), false)
        -- La fuente del alcance tiene hasta 3 decimales. Admitimos hasta 6
        -- y marcamos precisión adicional en lugar de redondearla sin aviso.
        or not coalesce(regexp_like(trim(unit_sales_original), '[-+]?[0-9]+([.][0-9]{1,6})?'), false)
        or id is null or store_nbr is null or item_nbr is null or unit_sales is null
    ) as has_invalid_numeric,
    (
        onpromotion is null
        or not coalesce(lower(trim(onpromotion_original)) in ('true', 'false'), false)
    ) as has_invalid_promotion
from tipado
