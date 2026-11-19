-- Casos auditados del CSV: distinguir localidad, traslado y coexistencia con Work Day.
with esperados as (
    select column1::date as date, column2::varchar as city,
           column3::boolean as holiday, column4::boolean as transferred,
           column5::boolean as work_day
    from values
        ('2016-08-10', 'Quito', false, true, false),
        ('2016-08-12', 'Quito', true, false, false),
        ('2017-04-12', 'Cuenca', false, true, false),
        ('2017-04-13', 'Cuenca', true, false, false),
        ('2017-04-12', 'Quito', false, false, false),
        ('2017-06-25', 'Quito', false, false, false),
        ('2017-06-25', 'Latacunga', true, false, false),
        ('2017-06-25', 'Machala', true, false, false),
        ('2017-06-25', 'Ibarra', true, false, false),
        ('2016-11-12', 'Ambato', true, false, true),
        ('2016-11-12', 'Quito', false, false, true)
)
select e.date, s.store_nbr, e.city, p.is_holiday, p.has_transferred_holiday, p.is_work_day
from esperados e
join {{ ref('brz_stores') }} s on e.city = s.city
left join {{ ref('slv_store_day_events') }} p on e.date = p.date and s.store_nbr = p.store_nbr
where p.date is null
   or (p.is_holiday is distinct from e.holiday)
   or (p.has_transferred_holiday is distinct from e.transferred)
   or (p.is_work_day is distinct from e.work_day)
