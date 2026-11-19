with gold_descrito as (
    select f.*, d.date
    from {{ ref('fct_oil_daily') }} f
    left join {{ ref('dim_date') }} d on f.date_key = d.date_key
)
select s.date as fecha_silver, g.date_key
from {{ ref('slv_oil_daily') }} s
full outer join gold_descrito g on s.date = g.date
where s.date is null or g.date_key is null
   or (s.oil_price_observed is distinct from g.oil_price_observed)
   or (s.oil_price_prepared is distinct from g.oil_price_prepared)
   or (s.has_source_row is distinct from g.has_source_row)
   or (s.is_source_price_missing is distinct from g.is_source_price_missing)
   or (s.is_imputed is distinct from g.is_imputed)
   or (s.price_reference_date is distinct from g.price_reference_date)
   or (s.price_age_days is distinct from g.price_age_days)
