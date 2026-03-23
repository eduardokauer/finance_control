# Finance Control Backend

Backend em FastAPI para controle financeiro pessoal, com importação de extratos e faturas, categorização, operação assistida no admin e análise determinística mensal.

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

4. A aplicação ficará disponível no serviço web configurado pelo `docker compose`.

## Testes
Suíte completa:

```bash
docker compose exec app pytest -q
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

## Visão mensal conciliada
A tela de análise agora prioriza a visão mensal conciliada como leitura principal do mês:

- os KPIs principais usam a visão conciliada
- o resumo executivo principal descreve a despesa líquida conciliada
- apenas faturas totalmente conciliadas entram no resumo principal
- pagamentos bancários conciliados de cartão deixam de inflar artificialmente a despesa principal

## Visão bruta como apoio
A visão bruta continua disponível na mesma tela como apoio e auditoria:

- comparação operacional dos números brutos do período
- conferência de pagamentos de fatura e outros itens técnicos
- base de apoio para investigar diferenças entre bruto e conciliado

Neste ciclo, gráficos históricos de 12 meses, categorias, alertas e ações recomendadas continuam apoiados na base atual, salvo ajustes mínimos de contexto.
