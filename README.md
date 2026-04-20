# Finance Control Backend

Backend em FastAPI para controle financeiro pessoal, com importação de extratos e faturas, categorização, operação assistida no admin e análise determinística mensal.

## Operating model
Este repositório guarda contexto técnico estável e regras de execução. O fluxo de trabalho do projeto acontece assim:
- ChatGPT Project refina a demanda e gera prompts
- Notion registra decisões curtas e a fatia atual
- Coder/Codex executa tecnicamente no repositório
- Claude escreve no Notion quando necessário

Leituras canônicas no repo:
- `docs/project_context.md` para contexto técnico estável
- `docs/coder_workflow.md` para execução técnica
- `docs/pm_workflow.md` para compatibilidade do processo
- `AGENTS.md` para regras recorrentes e leitura mínima

## Propósito
- importar extratos bancários e faturas de cartão
- categorizar transações com regras e ajustes manuais
- oferecer operação assistida via `/admin`
- gerar análise financeira determinística com foco mensal
- manter trilha auditável entre leitura bruta e leitura conciliada

## Stack
- Python 3.11
- FastAPI
- SQLAlchemy
- PostgreSQL
- Jinja2 + HTMX
- Pytest
- Docker Compose

## Ambiente local
1. Copie `.env.example` para `.env`.
2. Ajuste as variáveis necessárias.
3. Suba a stack:

```bash
docker compose up --build -d
```

No Windows/PowerShell, existe um wrapper nativo para os comandos mais comuns:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 up
```

4. A aplicação ficará disponível no serviço web configurado pelo `docker compose`.

## Testes
Suíte completa:

```bash
docker compose exec app pytest -q -n 4
```

Via PowerShell no Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test
```

Para PRs que alterem exclusivamente arquivos em `docs/`, rode o check rápido de documentação:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test-docs
```

Para recriar a stack com a última versão e só então rodar a suíte completa:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test-rebuild
```

Para forçar serial na investigação de um teste específico:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -Workers 0
```

Via `make`, a execução padrão também usa paralelismo. Para forçar serial:

```bash
make test PYTEST_WORKERS=0
```

Para PRs que alterem exclusivamente arquivos em `docs/`:

```bash
make test-docs
```

Para recriar containers antes da suíte completa:

```bash
make test-rebuild
```

Suíte focada da análise:

```bash
docker compose exec app pytest -q tests/test_analysis_service.py tests/test_admin_ui.py tests/test_admin_routes_smoke.py
```

Suíte focada de faturas:

```bash
docker compose exec app pytest -q tests/test_credit_card_bills.py tests/test_api.py
```

## Admin
- dashboard em `/admin`
- análise em `/admin/analysis`
- operações em `/admin/operations`
- transações em `/admin/transactions`
- regras em `/admin/rules`
- categorias em `/admin/categories`
- faturas em `/admin/credit-card-invoices`

## Conciliação assistida
O projeto já possui base para conciliação assistida de faturas de cartão, sem reclassificar fisicamente o domínio bruto:

- receitas reais da conta entram normalmente
- despesas reais da conta entram normalmente, exceto `bank_payment` conciliado
- `bank_payment` conciliado sai do gasto real
- itens `charge` de faturas `conciliated` entram como despesa real
- itens `credit` reduzem a despesa
- itens `payment` da própria fatura não entram no gasto real

Os status `pending_review`, `partially_conciliated` e `conflict` continuam fora da leitura principal conciliada.

## Sinais analíticos de conciliação
A análise expõe sinais auxiliares para dar visibilidade operacional à cobertura da conciliação, incluindo:

- quantas faturas conciliadas entraram na leitura principal
- quantas faturas ficaram fora por pendência, parcial ou conflito
- valor de pagamentos bancários excluídos por conciliação
- créditos técnicos de fatura identificados no período

Esses sinais continuam servindo como apoio operacional e auditoria, sem substituir o domínio bruto.

## Categorias em itens de fatura
A mesma base de categorias do extrato também passa a atender os itens de fatura:

- itens `charge` podem receber categoria de consumo normal
- itens `credit` continuam técnicos e não viram categoria de consumo
- itens `payment` continuam técnicos e não viram categoria de consumo
- regras determinísticas podem ser reaproveitadas com escopo por fonte (`bank_statement`, `credit_card_invoice_item` ou `both`)

Esta etapa prepara a base para futuras leituras analíticas por categoria nas faturas, sem alterar a lógica principal da conciliação.

## Direção da camada analítica
A camada analítica passa a ter 2 telas canônicas:

- uma tela única de gráficos e KPIs
- uma tela única de listagem e exploração de lançamentos

A migração será progressiva:

- criar as telas novas primeiro
- manter as telas antigas temporariamente
- migrar entradas e drilldowns aos poucos
- remover as telas antigas apenas após validação

A fatia atual prioriza a nova tela única de lançamentos, por auditabilidade e validação dos números.
