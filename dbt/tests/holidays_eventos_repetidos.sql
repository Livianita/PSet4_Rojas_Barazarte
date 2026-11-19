-- Repetir fecha es válido; repetir la descripción completa del mismo evento
-- debe investigarse. Esta prueba no elimina ninguna fila.
select date, event_type, locale, locale_name, description, transferred,
       count(*) as apariciones
from {{ ref('brz_holidays_events') }}
group by date, event_type, locale, locale_name, description, transferred
having count(*) > 1
