{% snapshot fornecedores_historico %}
{{ config(target_schema='analytics_history', unique_key='fornecedor_id',
          strategy='check', check_cols=['documento', 'razao_social'],
          invalidate_hard_deletes=True) }}
select fornecedor_id, documento, razao_social from {{ ref('stg_fornecedores') }}
{% endsnapshot %}
