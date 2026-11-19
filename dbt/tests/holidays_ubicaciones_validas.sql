-- Esta fuente ecuatoriana usa Ecuador, provincias o ciudades según su ámbito.
-- NOT EXISTS comprueba correspondencia sin multiplicar eventos por tienda.
select e.*
from {{ ref('brz_holidays_events') }} e
where (e.locale = 'National' and e.locale_name <> 'Ecuador')
   or (e.locale = 'Regional' and not exists (
       select 1 from {{ ref('brz_stores') }} s where s.state = e.locale_name
   ))
   or (e.locale = 'Local' and not exists (
       select 1 from {{ ref('brz_stores') }} s where s.city = e.locale_name
   ))
