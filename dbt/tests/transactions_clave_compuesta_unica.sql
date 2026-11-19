-- Ni fecha ni tienda son únicas por separado: debe serlo la combinación.
select date, store_nbr, count(*) as apariciones
from {{ ref('brz_transactions') }}
group by date, store_nbr
having count(*) > 1
