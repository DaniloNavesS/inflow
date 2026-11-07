# Airflow — base da orquestração E3

Airflow 3.4.0 em modo `standalone` para uso acadêmico local. Inicia interface/API,
scheduler e processador de DAGs. LocalExecutor executa as tarefas e um PostgreSQL
exclusivo armazena os metadados; o banco do projeto permanece separado.

## Subir e testar

Na raiz do projeto, com Docker Desktop ligado e `.env` configurado:

```powershell
docker compose --profile orchestration up -d --build --wait airflow
docker compose exec -T airflow python -m unittest discover -s /opt/inflow/tests -v
```

Alternativas: `make airflow-up` e `make airflow-test`.
`airflow-init` prepara as permissões do lake, cache CNPJ e estado do Airflow para
o usuário 50000. Reconstrua a imagem quando mudar o código.

Acesse **http://localhost:8080**, usuário **manu**. Consulte a senha local:

```powershell
docker compose exec airflow cat /opt/airflow/state/simple_auth_manager_passwords.json.generated
```

A senha e os logs persistem no volume `airflow_state`; os metadados ficam em
`airflow_db`. Não publique a senha. A interface está vinculada a `127.0.0.1`.
`AIRFLOW_PORT` permite mudar a porta no `.env`.

## Fluxo e política de execução

```text
escolher_origem → ingerir_origem → materializar_lake → verificar_freshness
        └──────────────────────→ materializar_lake
```

`inflow_pipeline` roda às **06h diariamente**, em `America/Sao_Paulo`:

- Por padrão, recarrega a origem com os parâmetros existentes no `.env`.
- Na execução manual, `recarregar_origem=false` usa o OLTP já carregado.
  A ingestão aparece como `skipped`, não como carga realizada.
- Até três tentativas por tarefa: execução inicial e dois retries, separados por um minuto.
- Uma execução do pipeline por vez. Não executar ingestão/lake manualmente ao
  mesmo tempo, pois esses comandos não passam pelo controle do Airflow.
- Falha na ingestão bloqueia o lake; falha no lake bloqueia a checagem final.
- `catchup=False`: ligar a agenda não dispara todos os dias passados. Não é backfill.

`inflow_freshness` roda no **minuto 15 de cada hora**, independentemente da carga:

- Consulta o monitoramento sem renovar a data do lake.
- Falha se a CLI detectar atraso, ausência de sucesso ou erro de consulta.
- A falha aparece na interface/logs; nenhum alerta externo foi configurado.

## Primeira execução e ativação

Os DAGs começam pausados. Na interface, abra `inflow_pipeline`, clique em
**Trigger** e desmarque `recarregar_origem` para validar o lake existente.
Confira ingestão `skipped`, lake `success` e freshness `success`.

O mesmo caminho pode ser validado pelo terminal, sem habilitar o agendamento:

```powershell
docker compose exec -T airflow python /opt/inflow/tests/smoke.py
```

Esse teste executa as tarefas de verdade e atualiza os arquivos do lake, mas não
valida o disparo pelo scheduler nem faz nova coleta das fontes.

Para habilitar os horários definidos:

```powershell
docker compose exec airflow dags unpause inflow_pipeline
docker compose exec airflow dags unpause inflow_freshness
```

Confira `INGESTION_YEAR` e `ENABLE_CNPJ_OWNERS` antes de habilitar a carga diária.
O enriquecimento CNPJ pode baixar gigabytes. Uma falha opcional nesse enriquecimento
é registrada pelo ingestor, mas não faz a tarefa inteira falhar: esse comportamento
já existe na ingestão e precisa ser considerado na política de qualidade.

O SLA inicial de 24 horas precisa considerar a duração da carga diária e dos
retries; uma execução mais lenta no dia seguinte pode excedê-lo. A métrica ainda
representa o lake, não a tabela dimensional final nem a idade da fonte.

Para pausar e parar:

```powershell
docker compose exec airflow dags pause inflow_pipeline
docker compose exec airflow dags pause inflow_freshness
docker compose stop airflow airflow-db
```

## Validação realizada em 07/11/2026

- Imagem construída e serviço saudável no Docker Desktop.
- Cinco testes do contrato dos DAGs passaram; nenhum erro de importação.
- Execução real via `smoke.py`, usando as 21.430 despesas existentes:
  `escolher_origem=success`, `ingerir_origem=skipped`,
  `materializar_lake=success`, `verificar_freshness=success`.
- Run do Airflow: `manual__2026-11-07T18:52:46.111804+00:00`.
- Run do lake: `d3ff5316-a445-47b1-8286-3fe5b0f38fa3`.
- PostgreSQL, Parquet e Delta concordaram nas duas consultas; soma preservada
  de R$ 32.290.271,35. Freshness retornou `fresh` com SLA de 24 horas.
- Horários e retries foram verificados na definição. Disparo automático, ingestão
  completa pelo DAG, recuperação após indisponibilidade e backfill ainda pendentes.

## Referências

- [Docker oficial do Airflow](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html)
- [TaskFlow](https://airflow.apache.org/docs/apache-airflow/stable/tutorial/taskflow.html)
- [BashOperator](https://airflow.apache.org/docs/apache-airflow-providers-standard/stable/operators/bash.html)
