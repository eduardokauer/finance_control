# Finance Control Backend

Python 3.11+ backend with FastAPI for ingesting Itau bank statements (OFX) and credit card bills (CSV), with structural validation, deduplication, deterministic categorization, reconciliation, and HTML financial analysis generation.

## Stack
- FastAPI
- Pydantic
- SQLAlchemy
- Postgres
- Pytest
- Docker

## Local Run With Docker
1. Copy `.env.example` to `.env`.
2. Adjust `API_TOKEN` if needed.
3. Start the stack:

```bash
docker compose up --build
```

API:
- `http://localhost:8000`

Health check:
- `GET /health`

Notes:
- The local Postgres container is started by `docker-compose.yml`.
- SQL migrations in `supabase/migrations` are applied automatically on the first database boot.

## Run In Background
```bash
docker compose up --build -d
docker compose ps
```

## Authentication
All protected endpoints require:

```text
Authorization: Bearer <API_TOKEN>
```

## Main Endpoints
- `POST /ingest/bank-statement`
- `POST /ingest/credit-card-bill`
- `GET /transactions`
- `POST /analysis/run`
- `GET /analysis/runs`
- `GET /health`

## Expected File Formats
### OFX
Required structure:
- `<OFX>`
- `<BANKTRANLIST>`
- `<STMTTRN>`

Required fields per transaction:
- `TRNTYPE`
- `DTPOSTED`
- `TRNAMT`
- `NAME`

### CSV
Expected columns, in this exact order:

```text
data,descricao,valor,tipo
```

Rules:
- Date format: `%d/%m/%Y`
- Value: decimal with comma or dot
- Encoding: UTF-8 or UTF-8 BOM

## Tests
Validated Docker flow:

```bash
docker compose up --build -d
docker compose exec app pytest -q
```

Run a specific file:

```bash
docker compose exec app pytest -q tests/test_api.py
docker compose exec app pytest -q tests/test_unit_rules.py
```

If the `app` service is not running, use:

```bash
docker compose run --rm app pytest -q
```

Local Python execution outside Docker:

```bash
pip install -r requirements.txt
pytest -q
```

## Stop The Stack
```bash
docker compose down
```

## Render Deploy
- Use the provided `Dockerfile`.
- Set `DATABASE_URL` to your Supabase Postgres connection string.
- Set a fixed `API_TOKEN` for Make.
