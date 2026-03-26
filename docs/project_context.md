# Project Context: finance_control

## Papel deste arquivo

`docs/project_context.md` é a fonte de verdade viva do projeto. Este arquivo registra o contexto do produto, o estado atual do sistema, as decisões já fechadas, a operação atual, os próximos passos recomendados e as limitações reais.

Arquivos complementares:
- `docs/pm_workflow.md`: regras da LLM que atua como PM/guia.
- `docs/codex_workflow.md`: regras do Codex como executor técnico.

Ordem de leitura recomendada:
- PM: ler `docs/project_context.md` e depois `docs/pm_workflow.md`.
- Codex: ler `docs/project_context.md` e depois `docs/codex_workflow.md`.
- Essas leituras devem acontecer antes de qualquer análise, planejamento, implementação ou validação ligada ao projeto.

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
- **Automação externa do MVP:** Make, wrapper PowerShell local, Google Forms e Google Drive fazem parte do contexto operacional do projeto para suportar fluxos do MVP, especialmente em torno de ingestão OFX.
- **Ingestão:**
  - OFX via endpoint autenticado por bearer token.
  - Fatura CSV Itaú via endpoint autenticado por bearer token e também via admin.
- **Auth:**
  - API protegida por bearer token fixo.
  - Admin protegido por senha + sessão.
- **Ambiente local:**
  - Windows com Docker Desktop é o ambiente operacional esperado.
  - `docker compose up --build -d` sobe `app` e `db`.
  - `Makefile` expõe atalhos básicos para subir stack e rodar testes quando `make` estiver disponível.
  - `scripts/dev.ps1` espelha os atalhos principais do `Makefile` para uso nativo no PowerShell/Windows.
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
- Separação conceitual entre visão de consumo e visão de fluxo de caixa definida no produto.
- Categorização determinística de itens de fatura implementada para `charge`.
- Regras manuais com `source_scope` implementadas.
- Reaplicação de categorias para itens de fatura implementada em nível de serviço.
- Exibição operacional da categoria dos itens de fatura no detalhe da fatura implementada.
- Edição manual direta da categoria de item `charge` de fatura na UI implementada.
- Preview de impacto e confirmação explícita antes de persistir a categoria manual de item de fatura implementados.
- Aplicação na base com preview, confirmação explícita, criação/atualização de regra e reaplicação dos itens de fatura existentes implementadas.
- Leitura mensal por categoria promovida para a visão de consumo do mês-base, com conta por `transaction_date` e cartão conciliado por `purchase_date`.
- Comparações mês a mês / ano a ano por categoria usando a mesma visão de consumo já adotada no mês-base implementadas na análise do admin.
- Alertas e ações recomendadas recalculados para priorizar sinais da visão de consumo quando falam de consumo, categorias e variação de gasto.
- Arquitetura da informação do admin reorganizada para separar Resumo, Análise detalhada, Conferência, Operação e Configuração.
- Home/resumo do admin simplificada para concentrar leitura financeira essencial, categorias prioritárias e atalhos de aprofundamento.
- Formulário de upload de fatura centralizado na tela de faturas do admin.
- Deduplicação forte implementada:
  - OFX usa controle por arquivo e transação canônica.
  - Fatura usa hash de arquivo e hash de linha por item importado.

### Ainda não implementado

- Conciliação automática de faturas.
- Vínculo automático ou definitivo com pagamento de conta além da conciliação manual assistida.
- Dashboard completo de fluxo de caixa como visão separada.
- Gráficos dedicados de evolução por categoria usando a visão de consumo.
- Migração ampla de toda a análise histórica para base conciliada.

## 4. Decisões de Domínio / Negócio Já Fechadas

### Papéis das fontes

- **Extrato bancário:** fonte oficial da liquidação.
- **Fatura do cartão:** fonte oficial da composição do gasto do cartão.

### Duas visões conceituais

- **Visão de consumo:** responde onde e com o que houve consumo real. Usa conta por `transaction_date`, cartão conciliado por `purchase_date` e mantém créditos genéricos de fatura em bloco técnico separado, fora das categorias de consumo. Na implementação atual, esse bloco técnico segue a `purchase_date` do próprio item importado quando ela existe, sem redistribuição artificial entre categorias.
- **Visão de fluxo de caixa:** responde quando o dinheiro entrou ou saiu da conta. Continua distinta da visão de consumo e ainda não foi promovida como dashboard completo no admin.

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
- Na visão de consumo:
  - transações da conta entram pela `transaction_date`;
  - itens `charge` de cartão entram pela `purchase_date`;
  - créditos genéricos sem vínculo confiável com uma compra permanecem fora das categorias, em ajuste técnico separado;
  - a competência temporal desse ajuste técnico segue a `purchase_date` do próprio item importado quando disponível;
  - isso é uma regra operacional da visão de consumo atual e não uma redistribuição artificial do crédito entre categorias;
  - `payment` da fatura e `bank_payment` conciliado ficam fora do consumo.
- Regras determinísticas usam `source_scope` para evitar reaproveitamento cego:
  - `bank_statement`
  - `credit_card_invoice_item`
  - `both`
- Um item `charge` de fatura só pode terminar com:
  - categoria existente na base oficial; ou
  - categoria oficial de não categorizado.
- Se fallback ou regra devolver categoria inexistente, o item cai no não categorizado oficial.

## 5. Estrutura Analítica Atual

- O admin agora separa a leitura em três entradas analíticas complementares:
  - **Resumo:** entrada principal, com KPIs conciliados, resumo executivo, categorias prioritárias da visão de consumo e alertas mais urgentes;
  - **Análise detalhada:** aprofundamento da visão de consumo, com breakdown categorial completo, comparações históricas, gráficos analíticos atuais, alertas e ações;
  - **Conferência:** visão bruta, cobertura da leitura principal, sinais auxiliares de conciliação, itens técnicos e HTML renderizado para auditoria.
- Essa reorganização é uma decisão explícita de arquitetura da informação do produto, feita antes da próxima etapa de gráficos dedicados por categoria.
- Os KPIs principais do mês usam a visão conciliada:
  - receitas
  - despesas
  - saldo
- O resumo executivo principal descreve a leitura conciliada do mês e sua cobertura.
- A tela deixa explícito:
  - quantas faturas conciliadas entraram na leitura principal;
  - quantas ficaram fora;
  - valor de pagamentos bancários excluídos por conciliação.
- O breakdown mensal por categoria do mês-base usa a visão de consumo:
  - transações válidas da conta por `transaction_date`;
  - itens `charge` de faturas `conciliated` por `purchase_date`;
  - ajuste técnico separado para `credit` genérico, pela `purchase_date` do próprio item quando disponível e sem redistribuição entre categorias;
  - exclusão de `payment` da própria fatura e de `bank_payment` conciliado do consumo.
- As comparações históricas por categoria do admin agora também usam a mesma visão de consumo:
  - mês-base vs mês anterior;
  - mês-base vs mesmo mês do ano anterior, quando houver base histórica suficiente;
  - créditos técnicos permanecem em bloco separado, pela data do próprio item importado quando disponível;
  - pagamentos conciliados continuam fora do consumo comparado.
- Alertas e ações recomendadas do admin agora seguem a mesma separação:
  - sinais ligados a consumo, categorias, concentração e variação usam a visão de consumo;
  - sinais gerais de saldo e cobertura do período continuam ancorados no resumo principal conciliado quando isso fizer mais sentido.
- A visão bruta continua disponível, mas foi rebaixada para a área de conferência para não poluir a home/resumo.

### O que ainda não foi migrado totalmente

- Gráficos dedicados de evolução por categoria na visão de consumo ainda não foram promovidos.
- Gráficos históricos de 12 meses continuam no suporte atual e ainda não foram reorganizados em uma camada visual própria da visão de consumo.
- A análise LLM continua separada da análise determinística e não é a leitura principal do admin.
- A visão de fluxo de caixa ainda não foi promovida como dashboard analítico separado.

### Dependências para próximas evoluções

- As próximas evoluções devem preferir incrementos já úteis para a análise ou para a operação principal, evitando preparações isoladas como destino final de um PR.
- Gráficos dedicados de evolução por categoria na visão de consumo, se fizer sentido depois da estabilização da leitura histórica atual.
- Consolidação final da operação manual de categorias na UI, se surgir nova lacuna real após o fluxo de aplicação na base já implementado.

## 6. Operação Admin Atual

### O admin já permite hoje

- **Arquitetura da informação**
  - usar `Resumo` como entrada principal do admin;
  - separar `Análise detalhada` como espaço de aprofundamento da visão de consumo;
  - manter `Conferência` para apoio, auditoria e diagnóstico;
  - concentrar lançamentos, faturas e reaplicação em `Operação`;
  - deixar `Central operacional`, regras e categorias agrupadas em `Configuração`.
- **Análise**
  - ver resumo financeiro enxuto por período, com KPIs conciliados, resumo executivo, categorias prioritárias e alertas prioritários;
  - ver análise detalhada por período;
  - promover a leitura conciliada como resumo principal;
  - ler categorias do mês-base na visão de consumo, com cartão por `purchase_date`;
  - comparar categorias do mês-base contra mês anterior e ano anterior na mesma visão de consumo;
  - receber alertas e ações recomendadas coerentes com a visão de consumo para temas de categoria e consumo;
  - manter visão bruta, cobertura e sinais auxiliares em uma área de conferência separada;
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
- A nova IA do admin já separa resumo, análise detalhada e conferência, mas a evolução visual por categoria ainda depende dos gráficos atuais e não de uma camada dedicada.
- A operação manual atual de categoria em itens de fatura já cobre ajuste pontual e aplicação na base, mas ainda depende de revisão humana caso o padrão desejado não seja recorrente o suficiente para virar regra.
- A visão de fluxo de caixa ainda não foi materializada como dashboard próprio.

## 7. Próximo Passo Atual e Sequência Recomendada

### Critério de evolução a partir daqui

- Priorizar o menor incremento seguro que já entregue valor perceptível ao usuário.
- Preferir entregas mais completas e úteis a fatias excessivamente fragmentadas.
- Evitar PRs que terminem apenas em preparação estrutural sem benefício funcional claro.
- Quando uma etapa preparatória for inevitável, mantê-la mínima e, de preferência, embutida em uma entrega maior que já exponha valor analítico ou operacional.
- Quando o tema ainda estiver em nível de produto, refiná-lo antes em iniciativa, épicos, histórias de usuário e só então em fatia pronta para execução.
- Prompt de execução para o Codex só deve nascer quando a fatia já tiver objetivo claro, valor entregue, fora de escopo, critérios de aceite e dependências principais suficientemente resolvidas ou explicitadas.

### Tema ativo do roadmap

- **Tema ativo:** evolução da home para painel principal orientado à decisão, com **Fluxo de caixa** como visão padrão e **Consumo** como modo alternável.
- **Objetivo de valor:** transformar a home na entrada principal do produto, com leitura mais visual, hierarquia mais clara e valor analítico percebido em poucos segundos.
- **Motivo da revisão:** a base categorial por consumo ficou mais consistente, mas a home continua com baixo valor percebido como painel principal. Para a entrada do produto, fluxo de caixa responde mais diretamente ao que entrou e saiu da conta no período, enquanto consumo permanece essencial como modo alternável e aprofundamento analítico.
- **Status do refinamento:** a direção do tema já foi revisada e consolidada o suficiente para não se perder em conversas futuras, mas o refinamento ainda está em andamento antes do handoff técnico.

### Estrutura de refinamento do tema ativo

- **Hierarquia correta de refinamento:** tema/iniciativa do roadmap -> épicos -> histórias de usuário -> fatias prontas para execução.
- **Épico:** objetivo amplo que organiza uma parte relevante do tema ativo.
- **História de usuário:** fatia menor, orientada a valor, que ajuda a entregar um épico.
- **Fatia pronta para execução:** recorte pequeno o suficiente para virar prompt do Codex sem ambiguidade de produto.

#### Épicos do tema ativo

1. **Home visual de fluxo de caixa**
   - construir a primeira versão da home com leitura predominantemente visual e fluxo de caixa como modo padrão.
2. **Leituras alternáveis e aprofundamento contextual**
   - manter consumo como modo alternável na home e conectar melhor a navegação com `Análise detalhada` e `Conferência`.
3. **Comparações por fonte e camadas de leitura**
   - preparar a evolução da home para leituras mensais e anuais por Extrato / Fatura / Conciliado sem perder clareza.

#### Primeiro épico refinado: Home visual de fluxo de caixa

- **Objetivo:** entregar a primeira home realmente orientada à decisão, com leitura rápida do mês e entrada mais visual para o produto.
- **Histórias de usuário iniciais já refinadas:**
  1. Como usuário, quero ver cards/KPIs visuais do mês para entender rapidamente o estado financeiro atual.
  2. Como usuário, quero ver um gráfico principal de evolução de 12 meses para perceber tendência e direção geral sem depender de leitura textual extensa.
  3. Como usuário, quero um comparativo visual das categorias do mês contra uma referência histórica para identificar desvios relevantes com rapidez.
  4. Como usuário, quero alternar entre Fluxo de caixa e Consumo na home para mudar a lente principal sem sair da entrada do sistema.
  5. Como usuário, quero atalhos claros para `Análise detalhada` e `Conferência` quando precisar aprofundar ou auditar a leitura principal.
- **Observação de produto:** revisão estética caminha junto com esse épico e não como trilha cosmética isolada posterior.

### Próximo passo recomendado

- Concluir o refinamento do primeiro épico até chegar à primeira fatia pronta para execução técnica do Codex.
- A candidata mais provável para esse primeiro handoff é a fatia de **cards/KPIs visuais do mês** na home em modo padrão de fluxo de caixa, já respeitando a navegação atual e os atalhos de aprofundamento.

### Fora de escopo imediato desta frente

- implementar a nova home neste momento;
- alterar templates, rotas, serviços ou lógica do produto antes do refinamento virar fatia pronta;
- discutir design visual final em nível de detalhe além do necessário para fechar direção de produto;
- dashboard completo de fluxo de caixa;
- novo motor analítico;
- mudanças de domínio financeiro já estabilizado;
- conciliação automática;
- reestruturação ampla dos serviços além do necessário para a navegação e a camada visual analítica.

## 8. Riscos e Limitações Conhecidas

- A leitura mensal e as comparações históricas por categoria já usam a visão de consumo, mas os gráficos dedicados dessa evolução ainda não foram promovidos.
- O resumo principal conciliado e a visão de consumo agora foram separados em páginas mais claras, mas o produto ainda depende de texto e hierarquia para não confundir consumo com fluxo de caixa.
- A visão bruta ainda é necessária para auditoria.
- A visão de consumo por categoria ainda depende de faturas totalmente conciliadas.
- O MVP continua dependente do layout oficial de OFX Itaú e CSV Itaú já suportados.
