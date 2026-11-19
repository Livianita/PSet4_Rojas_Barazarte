-- Validar el alcance de la extracción, sin descartar silenciosamente errores.
select v.id, v.date, v.item_nbr
from {{ ref('brz_sales') }} v
left join {{ ref('brz_items') }} i on v.item_nbr = i.item_nbr
where v.date < '2016-08-01'::date or v.date > '2017-08-15'::date
   or i.perishable is distinct from 1
