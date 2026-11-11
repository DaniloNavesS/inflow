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
escolher_origem → ingerir_origem → materializar_lake → transformar_modelos ┬→ verificar_freshness
        └──────────────────────→ materializar_lake                       └→ verificar_freshness_modelos
```

`inflow_pipeline` roda às **06h diariamente**, em `America/Sao_Paulo`:

- Por padrão, recarrega a origem com os parâmetros existentes no `.env`.
- Na execução manual, `recarregar_origem=false` usa o OLTP já carregado.
  A ingestão aparece como `skipped`, não como carga realizada.
- Até três tentativas por tarefa: execução inicial e dois retries, separados por um minuto.
- Uma execução do pipeline por vez. Não executar ingestão/lake manualmente ao
  mesmo tempo, pois esses comandos não passam pelo controle do Airflow.
- Falha na ingestão bloqueia o lake; falha no lake bloqueia os modelos; falha nos
  modelos bloqueia as duas checagens finais.
- `catchup=False`: ligar a agenda não dispara todos os dias passados. Não é backfill.

`inflow_freshness` roda no **minuto 15 de cada hora**, independentemente da carga:

- Consulta o monitoramento sem renovar a data do lake nem a dos modelos.
- Duas tarefas independentes: `verificar_freshness` (pipeline `analytics_lake`) e
  `verificar_freshness_modelos` (pipeline `dbt_models`). Um lake em dia não esconde
  modelos atrasados, e vice-versa.
- Falha se a CLI detectar atraso, ausência de sucesso ou erro de consulta.

## Transformações dbt

`transformar_modelos` executa `dbt build` (o mesmo comando de `make models`): seeds,
modelos, snapshot de fornecedores e testes, inclusive a suíte de qualidade. Um teste
reprovado faz a tarefa falhar. O dbt roda em um venv próprio na imagem do Airflow,
com as mesmas versões do serviço `modeling` (`dbt-core 1.12.6`, `dbt-postgres 1.9.1`),
e o projeto `analytics/dbt/` é copiado na construção: reconstrua a imagem após mudar
os modelos.

O wrapper `orchestration/bin/modelos.py` registra cada execução em
`monitoring.pipeline_runs` com o nome `dbt_models` (`success` ou `failed`, com o
código de saída do dbt). A tarefa usa o pool `inflow_exclusivo`, para não reconstruir
os modelos durante uma reingestão concorrente. Os modelos leem o OLTP, não o lake; a
dependência do lake é de ordem, para que uma carga com falha não publique modelos.
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

O SLA padrão é **26 horas**: agenda diária de 24 horas mais 2 horas de margem
operacional. O primeiro backfill real de 2024 em 08/11 levou 133 segundos sem
enriquecimento CNPJ; três execuções dessa duração e dois intervalos de retry
somariam cerca de 9 minutos. A margem não é garantia do pior caso: timeouts longos
ou CNPJ ativo exigem nova medição. A checagem horária detecta uma violação em até
aproximadamente uma hora adicional, se scheduler e banco estiverem disponíveis.
O mesmo limite vale para `dbt_models`, cuja execução levou de 14 a 17 segundos.
As métricas representam o último sucesso do lake e dos modelos, não a idade da fonte.
Se seu `.env` ainda definir 24, ele prevalece sobre o novo padrão: ajuste-o para 26
e recrie os serviços para adotar a política revisada.

## Backfill e concorrência

`inflow_backfill` é manual e exige `ano_inicio` e `ano_fim` (inclusive), entre
2000 e 2100, com no máximo 10 anos. A API CEAPS é anual. O fluxo valida o período,
reingere a origem, materializa o lake **completo** e reconstrói os modelos dbt. Nunca enviar um recorte ao
merge Delta, pois ele interpreta ausências como exclusões.

O pool `inflow_exclusivo` tem uma vaga e é criado na subida do Airflow. Ele evita
duas tarefas de ingestão/lake/dbt simultâneas, mas DAGs podem intercalar suas tarefas:
não é um bloqueio da execução inteira. Comandos manuais fora do Airflow não usam
esse pool.

## Alertas

Todas as tarefas registram JSON nos callbacks de retry e falha definitiva, com
`event`, `dag_id`, `task_id`, `run_id`, `attempt` e `error_type`. O texto original
da exceção e o contexto não são copiados, para não expor credenciais. Os eventos
são `task_retry` e `task_failed`. Não há envio para email ou serviço externo.

Para pausar e parar:

```powershell
docker compose exec airflow dags pause inflow_pipeline
docker compose exec airflow dags pause inflow_freshness
docker compose stop airflow airflow-db
```

## Checklist da frente de orquestração

| Item | Situação | Evidência |
|---|---|---|
| Dependências explícitas entre etapas | Atendido | ingestão → lake → dbt → freshness; falha bloqueia as seguintes (cenários abaixo) |
| Agendamento | Atendido | `inflow_pipeline` 06h e `inflow_freshness` de hora em hora; run disparado pelo scheduler |
| Retry | Atendido | Tentativa 1 `up_for_retry`, tentativa 2 `success`; três tentativas esgotadas bloqueiam o restante |
| Backfill | Atendido | `inflow_backfill` por intervalo de anos, executado duas vezes sem alterar contagens e somas |
| Transformações no fluxo | Atendido | `transformar_modelos` (`dbt build`) registrada como `dbt_models` |
| Freshness e SLA | Atendido | 26 h para lake e modelos, medidos separadamente; `fresh`, `stale` e `missing` demonstrados |
| Alerta de falha | Parcial | Log estruturado de retry e falha; sem envio externo |

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
- Naquela data, horários e retries haviam sido verificados somente na definição.

## Validação realizada em 08/11/2026 (sem dbt)

Ambiente isolado, CNPJ desligado. Backfill de 2024 a partir do banco vazio
(0 → 21.449 despesas, R$ 32.290.271,35, PostgreSQL = Delta) e repetido sem alteração;
retry com `materializar_lake` falhando na tentativa 1 e passando na 2; retries
esgotados (três falhas, freshness `upstream_failed`); SLA `fresh`/`stale`/`missing`;
run disparado pelo agendador `scheduled__2026-11-08T23:49:00+00:00` com sucesso.
O total passou de 21.430 para 21.449 por mudança da fonte, igual nas duas execuções.

## Validação realizada em 10/11/2026 (com dbt)

Mesmo ambiente isolado, base de 21.449 despesas, após a integração do dbt:

| Cenário | Run do Airflow | Resultado |
|---|---|---|
| Falha real do dbt | `manual__2026-11-11T00:17:58.650586+00:00` | `transformar_modelos` falhou nas 3 tentativas (teste de qualidade com erro de tipo); as duas checagens ficaram `upstream_failed`; 3 registros `dbt_models=failed` |
| Pipeline completo | `manual__2026-11-11T00:21:49.799482+00:00` | lake → dbt (17 s) → duas checagens `success` |
| Backfill 2024 (1ª) | `manual__2026-11-11T00:22:43.272743+00:00` | ingestão real 212 s, lake, dbt 15 s, checagens `success` |
| Backfill 2024 (2ª) | `manual__2026-11-11T00:26:40.535612+00:00` | `unchanged: true`: OLTP, Delta e `analytics_marts.fct_despesas` com 21.449 linhas e R$ 32.290.271,35 antes e depois |
| Retry | `manual__2026-11-11T00:28:20.734568+00:00` | `materializar_lake` tentativa 1 `up_for_retry`, tentativa 2 `success`; dbt e checagens `success` |
| Retries esgotados | `manual__2026-11-11T00:30:01.025854+00:00` | lake falhou 3 vezes; dbt e as duas checagens `upstream_failed` |
| SLA | — | lake e `dbt_models`: 26 h `fresh` (código 0), 0,001 h `stale` (código 1); pipeline sem execuções `missing` (código 1) |
| Agendador | `scheduled__2026-11-11T00:35:00+00:00` | disparado pelo scheduler: ingestão real, lake, dbt e as duas checagens `success` em 93 s; DAG pausado ao final |

Testes de contrato: 18 testes no contêiner (15 dos DAGs e 3 do wrapper dbt), 11 de
freshness e 7 do período de ingestão. Em clone limpo, sem `.env`: `make airflow-test`
(18), `make test-lake` (31) e a parte Docker de `make test-models` (223 testes dbt e
12 defeitos injetados detectados) passaram. O primeiro cenário revelou um erro já presente
na `develop`: `generate_series(smallint, smallint)` no teste
`competencias_sem_lacunas`, ambíguo depois que `mes` passou a `smallint`; corrigido
com cast explícito.

Para repetir os cenários, use **sempre** o projeto e o overlay isolados:

```powershell
docker compose -p inflow-e3-validation -f docker-compose.yml -f orchestration/tests/compose.validation.yml up -d --build --wait airflow
python orchestration/tests/validate_runtime.py backfill --start-year 2024 --end-year 2024
python orchestration/tests/validate_runtime.py backfill --start-year 2024 --end-year 2024 --expect-unchanged
python orchestration/tests/validate_runtime.py retry
python orchestration/tests/validate_runtime.py exhausted
python orchestration/tests/validate_runtime.py freshness
python orchestration/tests/validate_runtime.py scheduler
```

O overlay separa banco, lake, cache, metadados e rede; desliga o enriquecimento
CNPJ e não publica portas. Os cenários de falha desligam apenas esse banco de
validação. Os relatórios JSON e logs ficam em `resultados/e3-orquestracao/`
(ignorados pelo Git). O cenário `scheduler` usa um horário próximo, pausa o DAG
ao terminar e restaura a configuração do ambiente isolado. Não interromper esse
comando sem conferir a pausa do DAG. Os demais cenários usam `airflow dags test`.
Uma alteração na fonte entre backfills pode mudar os totais; investigar antes
de atribuir a diferença a duplicação.


## Referências

- [Docker oficial do Airflow](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html)
- [TaskFlow](https://airflow.apache.org/docs/apache-airflow/stable/tutorial/taskflow.html)
- [BashOperator](https://airflow.apache.org/docs/apache-airflow-providers-standard/stable/operators/bash.html)
