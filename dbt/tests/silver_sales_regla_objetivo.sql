-- Verificar el tratamiento explícito, no solo que el objetivo sea positivo.
select id, unit_sales_original, unit_sales_target, is_return
from {{ ref('slv_sales') }}
where unit_sales_target is distinct from greatest(unit_sales_original, 0)
   or is_return is distinct from (unit_sales_original < 0)
