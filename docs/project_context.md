# Project Context: finance_control

## Papel deste arquivo

Este arquivo guarda apenas contexto técnico estável do repositório. Ele não centraliza o processo de PM e não funciona como log longo de decisões.

Leituras de apoio:
- `README.md`: setup local, stack e comandos.
- `AGENTS.md`: regras recorrentes de execução.
- `docs/coder_workflow.md`: fluxo técnico do executor.
- `docs/pm_workflow.md`: stub de compatibilidade, quando necessário.

## Visão do projeto

- `finance_control` é um backend em FastAPI para controle financeiro pessoal.
- O sistema importa extratos OFX e faturas CSV Itaú, mantém conciliação assistida e expõe análise mensal determinística no admin.
- O foco técnico é rastreabilidade entre dado bruto, dado conciliado, categorização e leitura analítica.

## Stack estável

- Python 3.11
- FastAPI
- SQLAlchemy
- PostgreSQL
- Jinja2 + HTMX
- Pytest
- Docker Compose

## Restrições fixas

- OFX Itaú é a fonte oficial do extrato no MVP.
- CSV de fatura Itaú é a fonte oficial de fatura no MVP.
- Extrato representa liquidação.
- Fatura representa composição do gasto.
- Deduplicação precisa ser forte em ingestão e reprocessamento.
- A leitura conciliada não reclassifica fisicamente o domínio bruto.
- A leitura bruta continua disponível para auditoria.
- A análise principal permanece mensal e determinística.

## Estado técnico atual

- Admin web com shell consolidada e rotas principais para visão geral, análise, conferência, operações, transações, regras, categorias e faturas.
- Upload de OFX e de fatura centralizado no admin.
- Conciliação assistida de faturas com status `pending_review`, `partially_conciliated`, `conciliated` e `conflict`.
- Regras com `source_scope` para `bank_statement`, `credit_card_invoice_item` e `both`.
- Base única de categorias atendendo extrato e itens de fatura.
- Leitura bruta, leitura conciliada, visão de caixa e visão de competência coexistem como camadas analíticas.
- A camada analítica está organizada em 2 telas canônicas: uma tela única de gráficos em `/admin/analysis/charts` e uma tela única de listagem em `/admin/analysis/transactions`.
- As duas telas são autônomas, compartilham período global próprio e trocam navegação de forma explícita entre si.
- `/admin/analysis` permanece como alias de compatibilidade para a tela de gráficos.
- Comparações mensais e anuais, alertas e resumos operacionais já fazem parte do estado atual.

## Limitações conhecidas

- Conciliação automática de faturas ainda não faz parte da base atual.
- A decisão de conciliação continua manual.
- A leitura bruta segue necessária para conferência e auditoria.
- A leitura gerencial ainda pode evoluir, mas o contexto técnico já está estável.

## Regras de atualização

- Se estado, decisão ou limitação técnica mudar, atualize este arquivo no mesmo PR.
- Se o processo de execução mudar, atualize `docs/coder_workflow.md`.
- Se a compatibilidade do processo de PM mudar, atualize `docs/pm_workflow.md`.
