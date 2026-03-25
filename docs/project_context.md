# Project Context: finance_control

## Papel deste arquivo

`docs/project_context.md` é a fonte de verdade viva do projeto. Este arquivo registra o contexto do produto, o estado atual do sistema, as decisões já fechadas, a operação atual, os próximos passos recomendados e as limitações reais.

Arquivos complementares:
- `docs/pm_workflow.md`: regras da LLM que atua como PM/guia.
- `docs/codex_workflow.md`: regras do Codex como executor técnico.

Ordem de leitura recomendada:
- PM: ler `docs/project_context.md` e depois `docs/pm_workflow.md`.
- Codex: ler `docs/project_context.md` e depois `docs/codex_workflow.md`.

## 1. Visão Geral do Projeto

- **Nome:** `finance_control`
- **Objetivo principal:** centralizar ingestão, categorização, operação assistida e análise mensal de finanças pessoais.
- **Contexto de uso:** projeto pessoal de controle financeiro com foco em conta corrente, faturas de cartão e leitura mensal confiável.
- **Princípio do MVP:** priorizar fluxo operacional confiável, auditável e manualmente revisável antes de automações mais amplas.
- **Premissas fixas já tomadas:**
  - OFX do Itaú é a fonte oficial do extrato da conta corrente no MVP.
  - CSV de fatura Itaú é o formato oficial de fatura no MVP.
  - Extrato representa liquidação; fatura representa composição do gasto.
  - Leitura bruta continua disponível para apoio e auditoria.
  - Leitura conciliada evolui sem reclassificar fisicamente o domínio bruto.
  - Deduplicação precisa ser forte em ingestão e reprocessamento.
  - As próximas iterações devem priorizar o menor incremento seguro que já entregue valor funcional perceptível, preferencialmente na análise financeira, na leitura gerencial ou na operação principal do usuário.

## 2. Stack e Infraestrutura

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, Jinja2 e HTMX.
- **Banco:** PostgreSQL. Em produção, Supabase é usado como Postgres gerenciado. Em desenvolvimento local, o banco sobe via Docker Compose.
- **Deploy:** Render é a referência de deploy do backend.
- **Automação externa do MVP:** Make, Google Forms e Google Drive fazem parte do contexto operacional do projeto para suportar fluxos do MVP, especialmente em torno de ingestão OFX.
- **Ingestão:**
  - OFX via endpoint autenticado por bearer token.
  - Fatura CSV Itaú via endpoint autenticado por bearer token e também via admin.
- **Auth:**
  - API protegida por bearer token fixo.
  - Admin protegido por senha + sessão.
- **Ambiente local:**
  - Windows com Docker Desktop é o ambiente operacional esperado.
  - `docker compose up --build -d` sobe `app` e `db`.
  - `Makefile` expõe atalhos básicos para subir stack e rodar testes.
- **Testes:** `pytest`, com execução principal dentro do container.

## 3. Estado Atual do Sistema

### Implementado hoje

- Ingestão OFX funcionando.
- Fluxo Make + OFX funcionando ponta a ponta no contexto do MVP.
- Endpoint `POST /analysis/llm-email` existente.
- Admin web existente com autenticação por sessão.
- Análise determinística mensal evoluída e persistida.
- Importação de faturas CSV Itaú funcionando.
- Conciliação assistida manual de faturas implementada.
- Visão conciliada implementada.
- Visão conciliada promovida para leitura principal da tela de análise.
- Visão bruta mantida como apoio e auditoria.
- Categorização determinística de itens de fatura implementada para `charge`.
- Regras manuais com `source_scope` implementadas.
- Reaplicação de categorias para itens de fatura implementada em nível de serviço.
- Exibição operacional da categoria dos itens de fatura no detalhe da fatura implementada.
- Edição manual direta da categoria de item `charge` de fatura na UI implementada.
- Preview de impacto e confirmação explícita antes de persistir a categoria manual de item de fatura implementados.
- Aplicação na base com preview, confirmação explícita, criação/atualização de regra e reaplicação dos itens de fatura existentes implementadas.
- Leitura mensal por categoria promovida para a base conciliada do mês-base.
- Comparações mês a mês / ano a ano por categoria usando a visão conciliada já adotada no mês-base implementadas na análise do admin.
- Formulário de upload de fatura centralizado na tela de faturas do admin.
- Deduplicação forte implementada:
  - OFX usa controle por arquivo e transação canônica.
  - Fatura usa hash de arquivo e hash de linha por item importado.

### Ainda não implementado

- Conciliação automática de faturas.
- Vínculo automático ou definitivo com pagamento de conta além da conciliação manual assistida.
- Gráficos dedicados de evolução por categoria usando a base conciliada.
- Alertas e ações recomendadas recalculados sobre a nova base categorial de faturas.
- Migração ampla de toda a análise histórica para base conciliada.

## 4. Decisões de Domínio / Negócio Já Fechadas

### Papéis das fontes

- **Extrato bancário:** fonte oficial da liquidação.
- **Fatura do cartão:** fonte oficial da composição do gasto do cartão.

### Itens da fatura

- `charge`: representa consumo e pode entrar em leitura analítica de gasto.
- `credit`: representa crédito técnico / abatimento e não deve virar categoria de consumo normal.
- `payment`: representa liquidação técnica dentro da fatura e não entra como gasto real.

### Conciliação de fatura

- `PAGAMENTO EFETUADO` dentro da própria fatura **não** é a fonte oficial da conciliação.
- `DESCONTO NA FATURA` entra como componente técnico de quitação do tipo `invoice_credit`.
- A quitação da fatura é composta por:
  - `bank_payment`
  - `invoice_credit`
- Status válidos de conciliação:
  - `pending_review`
  - `partially_conciliated`
  - `conciliated`
  - `conflict`
- Regra de cardinalidade:
  - um pagamento bancário conciliado não pode ser usado em duas faturas diferentes;
  - uma fatura pode acumular mais de um `bank_payment`;
  - itens `invoice_credit` são derivados automaticamente dos créditos da própria fatura.
- Regra de candidatos do extrato:
  - o sistema só sugere transações com sinais compatíveis de pagamento de fatura;
  - a decisão continua manual;
  - o candidato precisa respeitar janela temporal, descrição e limite de saldo esperado;
  - o sistema bloqueia seleção que ultrapasse o saldo conciliável da fatura.

### Visão conciliada

- Só faturas com status `conciliated` entram na leitura principal conciliada.
- Faturas `pending_review`, `partially_conciliated` e `conflict` ficam fora da visão principal.
- `bank_payment` conciliado sai do gasto real principal.
- Itens `charge` de faturas conciliadas entram como despesa real.
- Itens `credit` abatem a despesa real.
- Itens `payment` da própria fatura não entram como gasto real.
- A visão bruta continua disponível como apoio, conferência e auditoria.

### Categorias

- Existe uma base única de categorias para o sistema.
- A mesma base atende extrato e itens de fatura.
- Itens `charge` de fatura podem receber categoria de consumo normal.
- Itens `credit` e `payment` continuam técnicos e não viram categoria de consumo.
- Regras determinísticas usam `source_scope` para evitar reaproveitamento cego:
  - `bank_statement`
  - `credit_card_invoice_item`
  - `both`
- Um item `charge` de fatura só pode terminar com:
  - categoria existente na base oficial; ou
  - categoria oficial de não categorizado.
- Se fallback ou regra devolver categoria inexistente, o item cai no não categorizado oficial.

## 5. Estrutura Analítica Atual

- A **visão principal** da tela de análise é a visão mensal conciliada.
- A **visão bruta** continua na mesma tela como apoio e auditoria.
- Os KPIs principais do mês usam a visão conciliada:
  - receitas
  - despesas
  - saldo
- O resumo executivo principal descreve a leitura conciliada do mês e sua cobertura.
- A tela deixa explícito:
  - quantas faturas conciliadas entraram na leitura principal;
  - quantas ficaram fora;
  - valor de pagamentos bancários excluídos por conciliação.
- O breakdown mensal por categoria do mês-base usa a visão conciliada:
  - transações válidas da conta;
  - itens `charge` de faturas `conciliated`;
  - ajuste técnico separado para `credit`;
  - exclusão de `payment` da própria fatura e de `bank_payment` conciliado do gasto principal.
- As comparações históricas por categoria do admin agora também usam a visão conciliada:
  - mês-base vs mês anterior;
  - mês-base vs mesmo mês do ano anterior, quando houver base histórica suficiente;
  - créditos técnicos permanecem em bloco separado;
  - pagamentos conciliados continuam fora do gasto principal comparado.

### O que ainda não foi migrado totalmente

- Gráficos históricos de 12 meses continuam apoiados na base atual.
- Alertas e ações recomendadas ainda não foram refeitos sobre a base categorial nova.
- A análise LLM continua separada da análise determinística e não é a leitura principal do admin.

### Dependências para próximas evoluções

- As próximas evoluções devem preferir incrementos já úteis para a análise ou para a operação principal, evitando preparações isoladas como destino final de um PR.
- Alertas e ações recomendadas sobre a base categorial conciliada, só depois da estabilização da leitura mensal e das comparações históricas.
- Gráficos dedicados de evolução por categoria na base conciliada, se fizer sentido depois da estabilização da leitura histórica atual.
- Consolidação final da operação manual de categorias na UI, se surgir nova lacuna real após o fluxo de aplicação na base já implementado.

## 6. Operação Admin Atual

### O admin já permite hoje

- **Análise**
  - ver análise determinística por período;
  - promover a leitura conciliada como resumo principal;
  - comparar categorias do mês-base contra mês anterior e ano anterior na mesma base conciliada;
  - manter visão bruta como apoio;
  - disparar nova análise determinística manualmente.
- **Transações**
  - listar, filtrar e revisar transações;
  - editar categoria e tipo da transação;
  - criar ou atualizar regra manual a partir da revisão;
  - fazer reclassificação em lote com preview.
- **Regras**
  - criar, editar, ativar, desativar e excluir regras;
  - definir `kind_mode`;
  - definir `source_scope`.
- **Categorias**
  - listar, criar e editar categorias da base oficial.
- **Faturas**
  - importar CSV Itaú;
  - listar faturas importadas;
  - ver detalhe da fatura;
  - ver itens, tipo técnico e categoria quando aplicável;
  - editar manualmente a categoria de item `charge` com preview de impacto e confirmação explícita;
  - aplicar a categoria na base com preview explícito dos itens impactados, confirmação, criação/atualização de regra e reaplicação dos itens elegíveis existentes.
- **Conciliação**
  - visualizar candidatos de pagamento;
  - vincular manualmente pagamentos do extrato;
  - desfazer vínculo;
  - acompanhar status e componentes da conciliação.
- **Categorização de itens de fatura**
  - categorização determinística de `charge` no serviço;
  - reaplicação em nível de serviço;
  - visualização da categoria no detalhe da fatura;
  - correção manual pontual via UI usando a base oficial de categorias;
  - criação/atualização de regra manual a partir do item de fatura com persistência para importações futuras elegíveis.

### Limitações operacionais atuais

- A decisão de conciliação ainda é manual.
- A leitura histórica por categoria já usa a base conciliada, mas ainda não há gráfico dedicado de evolução categorial nessa mesma base.
- A operação manual atual de categoria em itens de fatura já cobre ajuste pontual e aplicação na base, mas ainda depende de revisão humana caso o padrão desejado não seja recorrente o suficiente para virar regra.

## 7. Próximo Passo Atual e Sequência Recomendada

### Critério de evolução a partir daqui

- Priorizar o menor incremento seguro que já entregue valor perceptível ao usuário.
- Preferir entregas mais completas e úteis a fatias excessivamente fragmentadas.
- Evitar PRs que terminem apenas em preparação estrutural sem benefício funcional claro.
- Quando uma etapa preparatória for inevitável, mantê-la mínima e, de preferência, embutida em uma entrega maior que já exponha valor analítico ou operacional.

### Próximo passo atual do projeto

- Recalcular alertas e ações recomendadas sobre a base categorial conciliada, agora que a leitura mensal e as comparações históricas por categoria já usam a mesma lógica principal.

### Sequência recomendada a partir daqui

1. Recalcular alertas e ações recomendadas sobre a base categorial conciliada já estabilizada.
2. Se fizer sentido visualmente, promover gráficos dedicados de evolução por categoria usando essa mesma base conciliada.
3. Ajustar eventuais refinamentos operacionais residuais da categorização de faturas apenas se surgirem lacunas reais após o uso do fluxo atual.

## 8. Riscos e Limitações Conhecidas

- A leitura mensal e as comparações históricas por categoria já usam a base conciliada, mas os gráficos dedicados dessa evolução ainda não foram promovidos.
- Alertas e ações ainda não foram recalculados sobre a base categorial nova.
- A competência mensal continua conservadora.
- A visão bruta ainda é necessária para auditoria.
- A leitura conciliada por categoria ainda está concentrada no mês-base e depende de faturas totalmente conciliadas.
- O MVP continua dependente do layout oficial de OFX Itaú e CSV Itaú já suportados.
