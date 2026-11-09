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

O SLA padrão é **26 horas**: agenda diária de 24 horas mais 2 horas de margem
operacional. O primeiro backfill real de 2024 em 08/11 levou 133 segundos sem
enriquecimento CNPJ; três execuções dessa duração e dois intervalos de retry
somariam cerca de 9 minutos. A margem não é garantia do pior caso: timeouts longos
ou CNPJ ativo exigem nova medição. A checagem horária detecta uma violação em até
aproximadamente uma hora adicional, se scheduler e banco estiverem disponíveis.
A métrica representa o lake, não a tabela dimensional final nem a idade da fonte.
Se seu `.env` ainda definir 24, ele prevalece sobre o novo padrão: ajuste-o para 26
e recrie os serviços para adotar a política revisada.

## Backfill e concorrência

`inflow_backfill` é manual e exige `ano_inicio` e `ano_fim` (inclusive), entre
2000 e 2100, com no máximo 10 anos. A API CEAPS é anual. O fluxo valida o período,
reingere a origem e materializa o lake **completo**. Nunca enviar um recorte ao
merge Delta, pois ele interpreta ausências como exclusões.

O pool `inflow_exclusivo` tem uma vaga e é criado na subida do Airflow. Ele evita
duas tarefas de ingestão/lake simultâneas, mas DAGs podem intercalar suas tarefas:
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
  A validação complementar está registrada no diário abaixo.

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
