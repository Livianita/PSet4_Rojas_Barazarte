-- Agregar eventos ANTES de unirlos con ventas o transacciones.
with base as (
    select c.date, s.store_nbr, s.city, s.state
    from {{ ref('slv_calendar') }} c
    cross join {{ ref('brz_stores') }} s
)
select b.date, b.store_nbr,
       count(e.date) as applicable_event_count,
       sum(iff(e.event_type in ('Holiday', 'Transfer', 'Additional', 'Bridge')
               and not e.transferred, 1, 0)) as active_holiday_count,
       max(iff(e.event_type in ('Holiday', 'Transfer', 'Additional', 'Bridge')
               and not e.transferred, 1, 0)) = 1 as is_holiday,
       max(iff(e.event_type = 'Holiday' and e.transferred, 1, 0)) = 1 as has_transferred_holiday,
       max(iff(e.event_type = 'Transfer', 1, 0)) = 1 as is_transfer_day,
       max(iff(e.event_type = 'Additional', 1, 0)) = 1 as is_additional_day,
       max(iff(e.event_type = 'Bridge', 1, 0)) = 1 as is_bridge_day,
       max(iff(e.event_type = 'Work Day', 1, 0)) = 1 as is_work_day,
       max(iff(e.event_type = 'Event', 1, 0)) = 1 as has_special_event,
       nullif(listagg(distinct e.description, ' | ')
           within group (order by e.description), '') as event_descriptions
from base b
left join {{ ref('brz_holidays_events') }} e
    on b.date = e.date
   and (
       e.locale = 'National'
       or (e.locale = 'Regional' and e.locale_name = b.state)
       or (e.locale = 'Local' and e.locale_name = b.city)
   )
group by b.date, b.store_nbr
