-- Grano: una fecha–tienda–producto por cada día en que la tienda estuvo abierta,
-- desde la primera venta observada de la serie hasta el cierre del alcance.
--
-- Por qué: la documentación de la competencia en Kaggle indica que train.csv
-- omite las filas con unit_sales = 0 y que no informa si había stock. Sin esas
-- filas, un modelo nunca ve días sin venta (sobreestima) y una simulación de
-- reposición no puede contar sobrantes. Aquí se reconstruyen como cero, marcadas.
-- fct_sales no se modifica: sigue siendo el hecho de ventas observadas.
--
-- Decisiones:
--   * Inicio de la serie = primera venta observada: no se inventan ceros antes
--     de que el producto exista en la tienda.
--   * Tienda abierta = tiene transacciones o alguna venta de perecederos ese día.
--     Excluye cierres (p. ej. 25 de diciembre) sin asumir apertura. En el alcance
--     ambas señales coinciden (0 días con transacciones sin ventas; 2 al revés).
--   * onpromotion se imputa FALSE en los ceros, con is_onpromotion_imputed = TRUE.
--     Dejarlo NULL filtraría el objetivo: ninguna venta observada tiene promoción
--     NULL, así que "NULL" equivaldría a "venta cero" para un modelo.
--   * Medidas de origen (unit_sales_original, texto y procedencia) quedan NULL en
--     los ceros: no existen en la fuente. is_return es FALSE.
--   * is_observed, is_imputed_zero, is_onpromotion_imputed e is_after_last_sale
--     son marcas de auditoría y diagnóstico, NO variables predictoras: todas
--     revelan el objetivo o usan información futura (is_after_last_sale).
with ventas as (
    select * from {{ ref('fct_sales') }}
),
series as (
    select store_key, item_key,
           min(date_key) as first_date_key,
           max(date_key) as last_date_key
    from ventas
    group by store_key, item_key
),
tienda_abierta as (
    select date_key, store_key
    from {{ ref('fct_store_day_context') }}
    where has_transactions
    union
    select distinct date_key, store_key
    from ventas
),
grilla as (
    select a.date_key, s.store_key, s.item_key, s.last_date_key
    from series s
    join tienda_abierta a
      on a.store_key = s.store_key
     and a.date_key >= s.first_date_key
)
select g.date_key, g.store_key, g.item_key,
       v.id as source_id,
       v.unit_sales_original,
       coalesce(v.unit_sales_target, 0) as unit_sales_target,
       v.unit_sales_source_text,
       coalesce(v.is_return, false) as is_return,
       coalesce(v.onpromotion, false) as onpromotion,
       v.id is null as is_onpromotion_imputed,
       v.id is not null as is_observed,
       v.id is null as is_imputed_zero,
       g.date_key > g.last_date_key as is_after_last_sale,
       v.source_file, v.source_row_number, v.load_batch_id, v.source_sha256
from grilla g
left join ventas v
  on v.date_key = g.date_key
 and v.store_key = g.store_key
 and v.item_key = g.item_key
