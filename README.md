# Finance Control Backend

Python 3.11+ backend with FastAPI for ingesting Itau bank statements (OFX) and credit card bills (CSV), with structural validation, deduplication, deterministic categorization, reconciliation, HTML financial analysis generation, and manual transaction reclassification.

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
- `POST /transactions/reclassify`
- `POST /analysis/run`
- `GET /analysis/runs`
- `GET /health`

## Manual Reclassification
Use this endpoint to reclassify one transaction or a batch without creating a permanent rule.

```json
{
  "filters": {
    "transaction_ids": [1, 2, 3]
  },
  "category": "Outros",
  "transaction_kind": "expense",
  "should_count_in_spending": true,
  "notes": "manual exception"
}
```

You can also target a batch with filters such as `period_start`, `period_end`, `source_file_id`, `current_category`, `source_type`, or `description_contains`.

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
- `NAME` or `MEMO`

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
docker compose exec app pytest -vv
```

Convenience aliases via `Makefile`:

```bash
make up
make test
make test-fast
make test-e2e
```

Available aliases:
- `make up`
- `make down`
- `make logs`
- `make test`
- `make test-fast`
- `make test-e2e`
- `make test-api`
- `make test-unit`

Run a specific file:

```bash
docker compose exec app pytest -vv tests/test_api.py
docker compose exec app pytest -vv tests/test_unit_rules.py
docker compose exec app pytest -vv -s tests/test_e2e_ofx_import.py
```

Run only the fast tests:

```bash
docker compose exec app pytest -vv -m "not e2e"
```

Run only the end-to-end scenario:

```bash
docker compose exec app pytest -vv -s -m e2e
```

Run the end-to-end scenario with visible execution details:

```bash
docker compose exec app pytest -m e2e -vv -s
```

The end-to-end OFX scenario uses the fixture committed at `tests/fixtures/ofx/itau_statement_sample.ofx` and validates:
- import of a realistic Itau OFX file
- database persistence against the parsed file summary
- manual batch reclassification
- final analysis generation after overrides

If the `app` service is not running, use:

```bash
docker compose run --rm app pytest -vv
```

Local Python execution outside Docker:

```bash
pip install -r requirements.txt
pytest -vv
```

## Stop The Stack
```bash
docker compose down
```

## Render Deploy
- Use the provided `Dockerfile`.
- Set `DATABASE_URL` to your Supabase Postgres connection string.
- Set a fixed `API_TOKEN` for Make.
