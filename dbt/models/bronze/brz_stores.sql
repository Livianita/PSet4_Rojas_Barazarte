-- Una fila por tienda. No agregamos ni descartamos registros.
with origen as (
    select * from {{ source('favorita_raw', 'stores') }}
), tipado as (
    select
        try_to_number(nullif(trim(store_nbr), ''), 38, 0) as store_nbr,
        nullif(trim(city), '') as city,
        nullif(trim(state), '') as state,
        nullif(trim(type), '') as store_type,
        try_to_number(nullif(trim(cluster), ''), 38, 0) as store_cluster,
        -- Nombres más explícitos para TYPE y CLUSTER, conservando su origen.
        store_nbr as store_nbr_original,
        city as city_original,
        state as state_original,
        type as store_type_original,
        cluster as store_cluster_original,
        source_file, source_row_number, load_batch_id, loaded_at
    from origen
)
select *,
    (
        not coalesce(regexp_like(trim(store_nbr_original), '[0-9]+'), false)
        or not coalesce(regexp_like(trim(store_cluster_original), '[0-9]+'), false)
        or store_nbr is null or store_cluster is null
    ) as has_invalid_numeric
from tipado
