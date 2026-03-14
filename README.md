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
- For production or external databases, run migrations with `python -m app.core.migrate`.

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
- `POST /analysis/llm-email`
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

## LLM Email Preparation
Use `POST /analysis/llm-email` to prepare the deterministic email summary plus a compact payload for an external LLM call orchestrated by Make.

Request:

```json
{
  "period_start": "2026-03-01",
  "period_end": "2026-03-31",
  "trigger_source_file_id": 123
}
```

Response shape:

```json
{
  "summary_html": "<section>...</section>",
  "llm_payload": {
    "analysis_mode": "full_history",
    "generated_at": "2026-03-14T12:00:00+00:00",
    "currency": "BRL",
    "current_period": {
      "months_available_for_history": 12,
      "history_window_target_months": 12,
      "history_window_used_months": 12,
      "history_quality": "full"
    },
    "deterministic_summary": {},
    "historical_baseline": {},
    "current_vs_history": {},
    "signals": {},
    "guardrails": {}
  }
}
```

History fallback rules:
- `full_history`: 12 months available before the current period
- `partial_history`: 3 to 11 months available
- `insufficient_history`: 0 to 2 months available

The endpoint never calls an LLM directly. It only prepares deterministic numbers plus a concise historical payload for Make to forward to an external model.

## Expected File Formats
### Bank statement upload contract
`POST /ingest/bank-statement` must receive `multipart/form-data` with:
- `file`: required `.ofx` file
- `reference_id`: optional text field

Example:

```bash
curl -X POST http://localhost:8000/ingest/bank-statement \
  -H "Authorization: Bearer <API_TOKEN>" \
  -F "file=@tests/fixtures/ofx/itau_statement_sample.ofx;type=application/octet-stream" \
  -F "reference_id=manual-ofx-import"
```

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

Run SQL migrations manually against the configured `DATABASE_URL`:

```bash
python -m app.core.migrate
```

## Stop The Stack
```bash
docker compose down
```

## Render Deploy
- Use the provided `Dockerfile`.
- Set `DATABASE_URL` to your Supabase Postgres connection string using the SQLAlchemy format:
  `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require`
- Prefer the Supabase session pooler connection string when possible.
- Set a fixed `API_TOKEN` for Make.
- Set `ENVIRONMENT=prod`.
- Set `PORT` only if you need to override Render's default injected value.
- Configure the health check path as `/health`.
- Before the first deploy, or in a Render job/release step, run:

```bash
python -m app.core.migrate
```

- The app container on Render listens on the configured `PORT` automatically.
