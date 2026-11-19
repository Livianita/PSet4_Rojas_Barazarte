-- Clave de calendario estable: por ejemplo, 2016-08-01 -> 20160801.
select to_number(to_char(date, 'YYYYMMDD'), 8, 0) as date_key,
       date, year, month, day_of_month, day_of_week_iso,
       is_weekend, is_month_end, is_payday_proxy
from {{ ref('slv_calendar') }}
