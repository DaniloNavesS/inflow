# InFlow

Fonte transacional da plataforma de dados do Senado Federal para analisar CEAPS, fornecedores,
perfil e histórico parlamentar, comissões, presença plenária e estrutura de gabinete.

## Executar

Requer Docker com Compose.

```bash
cp .env.example .env
docker compose up --build
```

O comando cria o PostgreSQL, aplica as migrações em ordem e carrega dados públicos oficiais. Para
reprocessar sem recriar o banco:

```bash
docker compose run --rm ingestor
```

## Testar

```bash
docker compose run --rm ingestor pytest -q -p no:cacheprovider /tests
```

O banco fica disponível em `localhost:5433`, database `inflow_db`, usuário `inflow_user` e senha
`inflow_pass` por padrão. As variáveis podem ser alteradas no `.env`.

## Documentação

A matriz de perguntas, fontes, endpoints, modelagem, limitações e prova de presença via DSF está em
[`documentation/docs`](documentation/docs/intro.mdx). O ADR da E1 está em
[`docs/adr/0001-modelagem-do-sistema-de-origem.md`](docs/adr/0001-modelagem-do-sistema-de-origem.md).

Para gerar e servir o Docusaurus em `http://localhost:3000` sem instalar Node no host:

```bash
docker compose --profile docs up --build docs
```
