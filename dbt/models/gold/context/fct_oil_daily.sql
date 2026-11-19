-- Grano propio: una fecha; no repetir aquí el precio por producto o tienda.
select d.date_key, o.oil_price_observed, o.oil_price_prepared,
       o.has_source_row, o.is_source_price_missing, o.is_imputed,
       o.price_reference_date, o.price_age_days
from {{ ref('slv_oil_daily') }} o
left join {{ ref('dim_date') }} d on o.date = d.date
