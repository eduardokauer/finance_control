# Project Context: finance_control

## 1. Visão Geral do Projeto

- **Nome:** `finance_control`
- **Objetivo principal:** centralizar ingestão, categorização, operação assistida e análise mensal de finanças pessoais.
- **Contexto de uso:** projeto pessoal para controle financeiro com foco em conta corrente, faturas de cartão e leitura mensal confiável.
- **Princípio do MVP:** priorizar fluxo operacional confiável, auditável e manualmente revisável antes de automações mais amplas.
- **Premissas fixas já tomadas:**
  - OFX do Itaú é a fonte oficial do extrato da conta corrente no MVP.
  - CSV de fatura Itaú é o formato oficial de fatura no MVP.
  - Extrato e fatura não têm o mesmo papel: extrato representa liquidação; fatura representa composição do gasto.
  - Leitura bruta deve continuar disponível para auditoria.
  - Leitura conciliada deve evoluir sem reclassificar fisicamente o domínio bruto.
  - Deduplicação precisa ser forte em ingestão e reprocessamento.
  - `docs/project_context.md` passa a ser a fonte de verdade viva para continuidade do projeto.

## 2. Stack e Infraestrutura

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, Jinja2 e HTMX.
- **Banco:** PostgreSQL. Em produção, Supabase é usado como Postgres gerenciado. Em desenvolvimento local, a stack sobe Postgres via Docker Compose.
- **Deploy:** Render é a referência de deploy do backend.
- **Automação externa do MVP:** Make, Google Forms e Google Drive fazem parte do contexto operacional do projeto para alimentar fluxos de ingestão, especialmente OFX.
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
- **Serviços e componentes relevantes hoje:**
  - FastAPI
  - PostgreSQL / Supabase
  - Render
  - Docker Compose
  - Makefile
  - Google Forms / Google Drive / Make no contexto operacional do MVP

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
- Formulário de upload de fatura centralizado na tela de faturas do admin.
- Deduplicação forte implementada:
  - OFX usa controle por arquivo e transação canônica;
  - fatura usa hash de arquivo e hash de linha por item importado.

### Ainda não implementado

- Conciliação automática de faturas.
- Vínculo automático ou definitivo com pagamento de conta além da conciliação manual assistida.
- Edição manual direta da categoria de um item específico de fatura na UI.
- Preview de impacto para edição/correção manual de categoria em itens de fatura.
- Leitura analítica completa por categoria baseada na visão conciliada.
- Gráficos mês a mês / ano a ano por categoria usando a base conciliada.
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

### O que ainda não foi migrado totalmente

- Gráficos históricos de 12 meses continuam apoiados na base atual.
- Categorias mensais ainda não foram totalmente migradas para leitura conciliada com itens de fatura.
- Alertas e ações recomendadas ainda não foram refeitos sobre a base categorial nova.
- A análise LLM continua separada da análise determinística e não é a leitura principal do admin.

### Riscos e limitações analíticas atuais

- A visão categorial ainda é parcialmente ancorada no domínio bruto.
- A nova base de categorias de itens de fatura ainda não alimenta toda a análise histórica.
- A competência mensal continua conservadora e centrada na operação atual do MVP.
- A visão bruta ainda é necessária para explicar diferenças entre liquidação e composição do gasto.

### Dependências para próximas evoluções

- Operação manual segura de categoria dos itens de fatura.
- Preview de impacto antes de aplicar regra ou correção de categoria.
- Uso da visão conciliada como base para leituras por categoria.

## 6. Operação Admin Atual

### O admin já permite hoje

- **Análise**
  - ver análise determinística por período;
  - promover a leitura conciliada como resumo principal;
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
  - ver itens, tipo técnico e categoria quando aplicável.
- **Conciliação**
  - visualizar candidatos de pagamento;
  - vincular manualmente pagamentos do extrato;
  - desfazer vínculo;
  - acompanhar status e componentes da conciliação.
- **Categorização de itens de fatura**
  - categorização determinística de `charge` no serviço;
  - reaplicação em nível de serviço;
  - visualização da categoria no detalhe da fatura.

### Limitações operacionais atuais

- Não existe edição manual direta da categoria de um item de fatura na UI.
- Não existe preview de impacto específico para reaplicação em itens de fatura na UI.
- A decisão de conciliação ainda é manual.
- A leitura por categoria baseada em faturas ainda não foi promovida para o centro da análise.

## 7. Próximos Passos Recomendados

1. Implementar operação manual de categoria dos itens de fatura com preview de impacto.
2. Permitir aplicação de regra em itens de fatura com confirmação explícita.
3. Promover leitura analítica por categoria usando a visão conciliada.
4. Evoluir para comparações mês a mês / ano a ano por categoria.
5. Só depois recalcular alertas e ações recomendadas sobre a base categorial confiável.

## 8. Riscos e Limitações Conhecidas

- A análise por categoria ainda não foi totalmente migrada para a base conciliada.
- Alertas e ações ainda não foram recalculados sobre a base categorial nova.
- A competência mensal continua conservadora.
- A visão bruta ainda é necessária para auditoria.
- A UI de faturas ainda não oferece edição manual pontual de categoria por item.
- O MVP continua dependente do layout oficial de OFX Itaú e CSV Itaú já suportados.

## 9. Regras de Trabalho Obrigatórias

Estas regras devem ser seguidas em toda nova interação com Codex/LLM neste projeto.

1. Antes de executar qualquer nova tarefa, ler `docs/project_context.md`.
2. Preservar decisões já tomadas neste arquivo.
3. Não reabrir discussões já fechadas sem motivo explícito do usuário.
4. Sempre trabalhar com objetivo claro do PR e com fora de escopo explícito.
5. Sempre definir DoD objetivo antes de concluir uma entrega.
6. Sempre transformar itens relevantes do DoD em testes quando fizer sentido.
7. Sempre atualizar `docs/project_context.md` ao final de cada PR que altere estado, decisão, operação ou fluxo relevante.
8. Sempre revisar encoding, mojibake, BOM e formatação dos arquivos alterados.
9. Sempre executar a suíte completa antes de considerar a entrega concluída.
10. Só commitar e abrir PR depois de:
    - DoD cumprido;
    - contexto atualizado;
    - suíte completa verde.
11. Não abrir escopo sem alinhamento explícito.
12. Não inventar funcionalidades como se já existissem.
13. Manter a distinção entre domínio bruto, operação assistida e leitura analítica conciliada.

## 10. Template Operacional para Futuros PRs

Use este checklist mínimo em qualquer novo trabalho:

1. Ler `docs/project_context.md`.
2. Entender objetivo, restrições e fora de escopo do PR.
3. Confirmar decisões já fechadas que não podem ser quebradas.
4. Definir DoD explícito.
5. Implementar somente o necessário.
6. Atualizar ou adicionar testes coerentes com o DoD.
7. Atualizar `docs/project_context.md` se o PR alterar contexto relevante.
8. Revisar mojibake, BOM e formatação.
9. Rodar a suíte completa.
10. Só então fazer commit e abrir PR.
