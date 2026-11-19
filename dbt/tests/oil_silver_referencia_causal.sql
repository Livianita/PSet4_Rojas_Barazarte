-- Oráculo independiente del relleno por ventana: obtener la fecha máxima
-- con precio válido <= cada día y contrastar fecha, precio y antigüedad.
-- Evitar EXISTS correlacionado dentro de una disyunción: en la ejecución
-- diagnosticada devolvía 380 filas aun con las condiciones aisladas vacías.
with referencias_esperadas as (
    select c.date, max(o.date) as fecha_esperada
    from {{ ref('slv_calendar') }} c
    left join {{ ref('brz_oil') }} o
        on o.date <= c.date and o.dcoilwtico is not null
    group by c.date
)
select p.date, p.price_reference_date, e.fecha_esperada,
       p.oil_price_prepared, r.dcoilwtico as precio_esperado
from {{ ref('slv_oil_daily') }} p
join referencias_esperadas e on p.date = e.date
left join {{ ref('brz_oil') }} r on e.fecha_esperada = r.date
where (p.price_reference_date is distinct from e.fecha_esperada)
   or (p.oil_price_prepared is distinct from r.dcoilwtico)
   or (p.price_age_days is distinct from datediff('day', e.fecha_esperada, p.date))
