-- El calendario es la base: no perder fines de semana ni días sin cotización.
with calendario as (
    select date from {{ ref('slv_calendar') }}
), diario as (
    select c.date, o.dcoilwtico as oil_price_observed,
           o.date is not null as has_source_row,
           (o.date is not null and o.dcoilwtico is null) as is_source_price_missing
    from calendario c
    left join {{ ref('brz_oil') }} o on c.date = o.date
), semilla as (
    -- Si el primer día no tiene precio, permitir el último conocido ANTES
    -- del período. Nunca tomar un valor posterior para rellenar hacia atrás.
    select date, dcoilwtico as oil_price_observed,
           true as has_source_row, false as is_source_price_missing
    from {{ ref('brz_oil') }}
    where date < (select min(date) from calendario) and dcoilwtico is not null
    qualify row_number() over (order by date desc) = 1
), serie as (
    select * from diario
    union all
    select * from semilla
), preparado as (
    select *,
        last_value(oil_price_observed) ignore nulls over (
            order by date rows between unbounded preceding and current row
        ) as oil_price_prepared,
        last_value(case when oil_price_observed is not null then date end) ignore nulls over (
            order by date rows between unbounded preceding and current row
        ) as price_reference_date
    from serie
)
select p.date, p.oil_price_observed, p.oil_price_prepared,
       p.has_source_row, p.is_source_price_missing,
       (p.oil_price_observed is null and p.oil_price_prepared is not null) as is_imputed,
       p.price_reference_date,
       datediff('day', p.price_reference_date, p.date) as price_age_days
from preparado p
join calendario c on p.date = c.date
