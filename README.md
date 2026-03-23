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

## Ambiente local
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

## Endpoints principais
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

## Faturas de cartão no MVP
- cadastre primeiro um cartão na home do admin em `/admin`
- depois envie um arquivo CSV do Itaú junto com os campos obrigatórios:
  - `card_id`
  - `billing_month`
  - `billing_year`
  - `due_date`
  - `total_amount_brl`
- campos opcionais:
  - `closing_date`
  - `notes`
- o upload da fatura é manual, um arquivo por vez, com `multipart/form-data`
- o sistema bloqueia:
  - reenvio do mesmo arquivo
  - outra fatura para o mesmo cartão e competência
  - estrutura inválida do CSV

## Admin de faturas
- listagem operacional: `/admin/credit-card-invoices`
- detalhe da fatura: `/admin/credit-card-invoices/<invoice_id>`
- a home do admin em `/admin` agora abre a análise
- a central operacional antiga ficou disponível no menu em `/admin/operations`

## Conciliação manual assistida de faturas
- a fonte oficial da liquidação é o extrato bancário, não o item `PAGAMENTO EFETUADO` dentro da própria fatura
- a tela de detalhe da fatura mostra candidatos de pagamento do extrato em uma janela operacional de `due_date - 20 dias` até `due_date + 40 dias`, com sinais simples de aderência para apoiar a revisão
- o usuário pode selecionar um ou mais pagamentos bancários para conciliar manualmente a fatura; a seleção continua manual e os sinais não substituem a decisão humana
- descontos da própria fatura, como `DESCONTO NA FATURA`, entram automaticamente como `invoice_credit`
- a tela mostra:
  - total bruto de cobranças
  - créditos técnicos da fatura
  - pagamentos bancários conciliados
  - total conciliado
  - saldo restante
  - status da conciliação
- vínculos ativos podem ser desfeitos na própria tela de detalhe da fatura
- uma transação bancária não pode ser conciliada em duas faturas diferentes

## Sinais analíticos de conciliação
- a aplicação agora expõe sinais auxiliares derivados da conciliação sem alterar os totais finais do consolidado principal
- no admin de lançamentos, transações do extrato já vinculadas como `bank_payment` conciliado aparecem identificadas como item técnico
- na tela de análise, há um bloco auxiliar com:
  - pagamentos de fatura conciliados no período
  - créditos técnicos de fatura no período
  - quantidade de faturas por status de conciliação
- esta etapa é preparatória para futura integração completa da fatura na análise consolidada; neste PR os KPIs principais continuam iguais

## Visão mensal conciliada
- a tela de análise agora também mostra uma visão mensal conciliada, separada da visão atual/bruta
- a visão atual continua disponível e inalterada
- a visão conciliada considera apenas faturas com status `conciliated`
- nessa leitura:
  - pagamentos bancários conciliados de cartão saem do gasto real do mês
  - itens `charge` das faturas conciliadas entram como despesa real de cartão
  - itens `credit` reduzem a despesa do cartão sem virar receita operacional
  - itens `payment` da própria fatura continuam fora do gasto real
- faturas `pending_review`, `partially_conciliated` e `conflict` ficam fora do consolidado conciliado principal e aparecem apenas em indicadores auxiliares

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

