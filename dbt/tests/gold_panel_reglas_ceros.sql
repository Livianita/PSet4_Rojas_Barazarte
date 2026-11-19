-- Reglas de negocio del panel:
--   * ningún objetivo es negativo y los marcadores son excluyentes;
--   * un cero reconstruido tiene objetivo 0, sin ID ni medidas de origen,
--     sin devolución y con promoción imputada FALSE (marcada);
--   * una venta observada tiene ID (la conciliación fila a fila con fct_sales
--     está en gold_panel_conserva_ventas);
--   * ningún cero cae en un día con la tienda cerrada (sin transacciones ni ventas).
with panel as (
    select * from {{ ref('fct_sales_panel') }}
),
tienda_abierta as (
    select date_key, store_key from {{ ref('fct_store_day_context') }} where has_transactions
    union
    select distinct date_key, store_key from {{ ref('fct_sales') }}
)
select p.date_key, p.store_key, p.item_key, 'regla de valores' as falla
from panel p
where p.unit_sales_target < 0
   or p.is_observed = p.is_imputed_zero
   or p.is_onpromotion_imputed <> p.is_imputed_zero
   or (p.is_imputed_zero and (p.unit_sales_target <> 0
                              or p.source_id is not null
                              or p.unit_sales_original is not null
                              or p.is_return
                              or p.onpromotion))
   or (p.is_observed and p.source_id is null)
union all
select p.date_key, p.store_key, p.item_key, 'cero en tienda cerrada'
from panel p
left join tienda_abierta a using (date_key, store_key)
where a.date_key is null
