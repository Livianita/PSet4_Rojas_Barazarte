{% macro generate_schema_name(custom_schema_name, node) -%}
    {# El proyecto académico usa esquemas explícitos en su propia base. #}
    {% if custom_schema_name is none %}
        {{ target.schema }}
    {% else %}
        {% set capa = custom_schema_name | trim | upper %}
        {% if capa == 'DBT_TEST__AUDIT' %}
            {# dbt calcula también el esquema interno de auditoría de tests. #}
            {{ target.schema }}_DBT_TEST__AUDIT
        {% elif capa not in ['BRONZE', 'SILVER', 'GOLD', 'ANALYTICS'] %}
            {{ exceptions.raise_compiler_error('Esquema no permitido para las capas PSET2: ' ~ capa) }}
        {% else %}
            {{ capa }}
        {% endif %}
    {% endif %}
{%- endmacro %}
