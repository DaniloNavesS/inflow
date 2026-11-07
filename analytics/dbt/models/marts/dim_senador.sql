-- Partido e UF atuais: não usar para atribuição histórica de gastos.
select * from {{ ref('stg_senadores') }}
