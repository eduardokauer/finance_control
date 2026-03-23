# Finance Control Backend

Backend em FastAPI para controle financeiro pessoal.

## Proposito
- importar extratos bancarios e faturas
- categorizar transacoes
- permitir correcoes manuais via `/admin`
- gerar analise financeira deterministica

## Stack
- Python 3.11
- FastAPI
- SQLAlchemy
- Postgres
- Jinja2 + HTMX
- Pytest
- Docker

## Ambiente local
1. Copie `.env.example` para `.env`.
2. Ajuste as variaveis necessarias.
3. Suba a stack:

```bash
docker compose up --build -d
```

## Testes
Suite completa:

```bash
docker compose exec app pytest -q
```

Suite focada da analise:

```bash
docker compose exec app pytest -q tests/test_analysis_service.py tests/test_admin_ui.py tests/test_admin_routes_smoke.py
```

## Analise mensal conciliada
- a tela de analise agora prioriza a visao mensal conciliada como leitura principal do mes
- a visao bruta continua disponivel como apoio e auditoria
- apenas faturas com status `conciliated` entram no resumo principal
- pagamentos bancarios conciliados de cartao deixam de inflar artificialmente a despesa principal
- faturas `pending_review`, `partially_conciliated` e `conflict` ficam fora da leitura principal
- graficos historicos de 12 meses, categorias, alertas e acoes seguem na base atual neste ciclo

## Admin
- dashboard em `/admin`
- analise em `/admin/analysis`
- operacoes em `/admin/operations`
- faturas em `/admin/credit-card-invoices`
