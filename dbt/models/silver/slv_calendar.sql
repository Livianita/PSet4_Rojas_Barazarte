-- Calendario histórico del alcance PSET1: 380 días inclusivos.
with dias as (
    select row_number() over (order by seq4()) - 1 as desplazamiento
    from table(generator(rowcount => 380))
), fechas as (
    select dateadd('day', desplazamiento, '2016-08-01'::date)::date as date
    from dias
)
select date,
       year(date) as year,
       month(date) as month,
       day(date) as day_of_month,
       dayofweekiso(date) as day_of_week_iso,
       dayofweekiso(date) in (6, 7) as is_weekend,
       date = last_day(date) as is_month_end,
       (day(date) = 15 or date = last_day(date)) as is_payday_proxy
from fechas
