# InFlow

Fonte transacional de dados públicos do Senado Federal para analisar CEAPS, fornecedores,
histórico parlamentar, comissões, presença plenária e estrutura de gabinete.

## Executar

Requer Docker, Docker Compose e GNU Make.

```bash
cp .env.example .env
make ingestion
```

O comando inicia o PostgreSQL, aplica as migrations pendentes e executa a carga. O banco fica em
`localhost:5433` por padrão. Para reprocessar, execute novamente `make ingestion`.

## Testar

```bash
make test
```

## Documentação

Use `make docs` para servir o Docusaurus em `http://localhost:3000`. Perguntas, fontes, endpoints,
modelagem, limitações e decisões arquiteturais estão na
[documentação completa](https://danilonavess.github.io/inflow/docs/intro).
