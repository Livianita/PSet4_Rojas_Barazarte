select p.date
from {{ ref('slv_calendar') }} c
left join {{ ref('brz_oil') }} o on c.date = o.date
left join {{ ref('slv_oil_daily') }} p on c.date = p.date
where p.date is null
   or p.oil_price_observed is distinct from o.dcoilwtico
   or p.has_source_row is distinct from (o.date is not null)
   or p.is_source_price_missing is distinct from (o.date is not null and o.dcoilwtico is null)
   or p.is_imputed is distinct from (p.oil_price_observed is null and p.oil_price_prepared is not null)
