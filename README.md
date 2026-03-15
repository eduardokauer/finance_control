# Finance Control Backend

Backend em FastAPI para controle financeiro pessoal: ingestão de extratos, categorização, análise determinística e interface administrativa web para revisão e correção dos lançamentos.

## Propósito
- importar extratos bancários e faturas
- categorizar transações
- permitir correções manuais via `/admin`
- gerar análise financeira e payload para fluxo com Make/LLM

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

Observações:
- o app aplica migrations automaticamente no startup
- o Bearer token da API é separado do login por senha da interface admin

## Autenticação
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
Suíte completa:

```bash
docker compose exec app pytest -q
```

Validação completa do zero, com reset local, boot, testes, login admin, ingestão OFX e `analysis/llm-email`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate_local_reset.ps1
```

Atalhos úteis:

```bash
make up
make down
make logs
make test
```

## Desenvolvimento
Parar a stack:

```bash
docker compose down
```

Parar e zerar o banco local:

```bash
docker compose down -v
```

## Produção
Variáveis recomendadas:

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

O container já sobe com migrations antes da aplicação:

```bash
/bin/sh -c "python -m app.core.migrate && python -m app.run"
```

Após deploy:
- API: `https://<seu-servico>.onrender.com`
- Admin UI: `https://<seu-servico>.onrender.com/admin`
