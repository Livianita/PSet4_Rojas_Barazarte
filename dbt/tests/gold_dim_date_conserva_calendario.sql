select s.date as fecha_silver, d.date as fecha_gold
from {{ ref('slv_calendar') }} s
full outer join {{ ref('dim_date') }} d on s.date = d.date
where s.date is null or d.date is null
   or (d.date_key is distinct from to_number(to_char(s.date, 'YYYYMMDD'), 8, 0))
   or (s.year is distinct from d.year)
   or (s.month is distinct from d.month)
   or (s.day_of_month is distinct from d.day_of_month)
   or (s.day_of_week_iso is distinct from d.day_of_week_iso)
   or (s.is_weekend is distinct from d.is_weekend)
   or (s.is_month_end is distinct from d.is_month_end)
   or (s.is_payday_proxy is distinct from d.is_payday_proxy)
