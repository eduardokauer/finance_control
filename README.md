# Finance Control Backend

Backend em FastAPI para controle financeiro pessoal: ingestÃ£o de extratos, categorizaÃ§Ã£o, anÃ¡lise determinÃ­stica e interface administrativa web para revisÃ£o e correÃ§Ã£o dos lanÃ§amentos.

## PropÃ³sito
- importar extratos bancÃ¡rios e faturas
- categorizar transaÃ§Ãµes
- permitir correÃ§Ãµes manuais via `/admin`
- gerar anÃ¡lise financeira e payload para fluxo com Make/LLM

## Stack
- Python 3.11
- FastAPI
- SQLAlchemy
- Postgres
- Jinja2 + HTMX
- Pytest
- Docker

## Ambiente Local
1. Copie `.env.example` para `.env`
2. Ajuste pelo menos:

```env
API_TOKEN=troque-este-token
ADMIN_UI_PASSWORD=troque-esta-senha
ADMIN_UI_SESSION_SECRET=um-segredo-longo
```

3. Suba a stack:

```bash
docker compose up --build -d
```

4. Acesse:
- API: `http://localhost:8000`
- Admin UI: `http://localhost:8000/admin`
- Health: `http://localhost:8000/health`

ObservaÃ§Ãµes:
- o app aplica migrations automaticamente no startup
- o Bearer token da API Ã© separado do login por senha da interface admin

## AutenticaÃ§Ã£o
- API protegida: `Authorization: Bearer <API_TOKEN>`
- Admin UI:
  - login em `/admin/login`
  - senha definida por `ADMIN_UI_PASSWORD`

## Endpoints Principais
- `POST /ingest/bank-statement`
- `POST /ingest/credit-card-bill`
- `GET /transactions`
- `POST /transactions/reclassify`
- `POST /analysis/run`
- `POST /analysis/llm-email`
- `GET /analysis/runs`
- `GET /health`

## Testes
SuÃ­te completa:

```bash
docker compose exec app pytest -q
```

ValidaÃ§Ã£o completa do zero, com reset local, boot, testes, login admin, ingestÃ£o OFX e `analysis/llm-email`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate_local_reset.ps1
```

Atalhos Ãºteis:

```bash
make up
make down
make logs
make test
```

## Faturas de CartÃ£o no MVP
- cadastre primeiro um cartÃ£o na home do admin em `/admin`
- depois envie um arquivo CSV do ItaÃº junto com os campos obrigatÃ³rios:
  - `card_id`
  - `billing_month`
  - `billing_year`
  - `due_date`
  - `total_amount_brl`
- campos opcionais:
  - `closing_date`
  - `notes`
- o upload da fatura Ã© manual, um arquivo por vez, com `multipart/form-data`
- o sistema bloqueia:
  - reenvio do mesmo arquivo
  - outra fatura para o mesmo cartÃ£o e competÃªncia
  - estrutura invÃ¡lida do CSV

## Admin de Faturas
- listagem operacional: `/admin/credit-card-invoices`
- detalhe da fatura: `/admin/credit-card-invoices/<invoice_id>`
- a home do admin em `/admin` também mostra as últimas faturas importadas com link para o detalhe
## Desenvolvimento
Parar a stack:

```bash
docker compose down
```

Parar e zerar o banco local:

```bash
docker compose down -v
```

## ProduÃ§Ã£o
VariÃ¡veis recomendadas:

```env
ENVIRONMENT=prod
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require
API_TOKEN=token-forte
ADMIN_UI_PASSWORD=senha-forte
ADMIN_UI_SESSION_SECRET=segredo-longo-e-aleatorio
```

## Deploy no Render
- usar o `Dockerfile` do projeto
- deixar `Docker Command` e `Start Command` vazios no plano free
- configurar health check em `/health`
- configurar estas env vars:
  - `DATABASE_URL`
  - `API_TOKEN`
  - `ADMIN_UI_PASSWORD`
  - `ADMIN_UI_SESSION_SECRET`
  - `ENVIRONMENT=prod`

O container jÃ¡ sobe com migrations antes da aplicaÃ§Ã£o:

```bash
/bin/sh -c "python -m app.core.migrate && python -m app.run"
```

ApÃ³s deploy:
- API: `https://<seu-servico>.onrender.com`
- Admin UI: `https://<seu-servico>.onrender.com/admin`

