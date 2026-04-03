# Project Context: finance_control

## Papel deste arquivo

`docs/project_context.md` é a fonte de verdade viva do projeto. Ele registra o contexto do produto, o estado atual do sistema, as decisões já fechadas, a operação atual, as limitações reais e o roadmap do produto.

Arquivos complementares:
- `docs/pm_workflow.md`: regras da LLM que atua como PM/guia.
- `docs/pm_cycle_start_prompt.md`: prompt canônico para iniciar um novo ciclo PM/LLM.
- `docs/codex_workflow.md`: regras do Codex como executor técnico.
- `docs/admin_readequacao_control.md`: controle operacional da readequacao global do admin a partir do template original.

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
- **Automação externa do MVP:** Make, wrapper PowerShell local, Google Forms e Google Drive suportam fluxos operacionais do MVP, especialmente em torno de ingestão OFX.
- **Ingestão:**
  - OFX via endpoint autenticado por bearer token.
  - Fatura CSV Itaú via endpoint autenticado por bearer token e também via admin.
- **Auth:**
  - API protegida por bearer token fixo.
  - Admin protegido por senha + sessão.
- **Ambiente local:**
  - Windows com Docker Desktop é o ambiente operacional esperado.
  - `docker compose up --build -d` sobe `app` e `db`.
  - `Makefile` expõe atalhos básicos para subir a stack e rodar testes quando `make` estiver disponível.
  - `scripts/dev.ps1` espelha os atalhos principais do `Makefile` para uso nativo no PowerShell/Windows, incluindo um fluxo de `test-rebuild` para recriar a stack antes da suíte completa e um `test-docs` rápido para PRs que alterem exclusivamente arquivos em `docs/`.
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
- Visão conciliada implementada e promovida para leitura principal do resumo do período.
- Visão bruta mantida como apoio e auditoria.
- Separação conceitual entre visão de consumo e visão de fluxo de caixa definida no produto.
- Categorização determinística de itens de fatura implementada para `charge`.
- Regras manuais com `source_scope` implementadas.
- Reaplicação de categorias para itens de fatura implementada em nível de serviço.
- Exibição operacional, edição manual pontual e aplicação na base com preview para categorias de itens `charge` já implementadas no admin.
- Leitura mensal por categoria promovida para a visão de consumo do mês-base, com conta por `transaction_date` e cartão conciliado por `purchase_date`.
- Comparações mês a mês / ano a ano por categoria usando a mesma visão de consumo já adotada no mês-base implementadas na análise do admin.
- Alertas e ações recomendadas recalculados para priorizar sinais da visão de consumo quando falam de consumo, categorias e variação de gasto.
- Arquitetura da informação do admin reorganizada para separar Resumo, Análise detalhada, Conferência, Operação e Configuração.
- Shell global do admin redesenhada com sidebar persistente no desktop, drawer no tablet/mobile e topbar fixa nas telas autenticadas.
- Home/resumo do admin simplificada para concentrar leitura financeira essencial, categorias prioritárias e atalhos de aprofundamento.
- Home/resumo do admin evoluída para alternar entre `Visão de Caixa` e `Visão de Competência`, com cards, resumo executivo e alertas coerentes com a lente ativa.
- Gráfico principal da home/resumo materializado com controle temporal local (`Ano` e `Últimos 12 meses`), dropdown de ano, abas curtas de comparação por métrica e convenção visual com barras para entradas/saídas ou receitas/despesas e linha para fluxo/resultado.
- Bloco-resumo com comparativo visual das Top 5 categorias de consumo do mês-base materializado apenas na `Visão de Competência`, com referência padrão no mês anterior.
- Barra de contexto padronizada no topo de `Resumo`, `Análise detalhada` e `Conferência`, separando breadcrumb, controles globais da página, chips de contexto e foco contextual por origem.
- Navegação contextual entre `Resumo`, `Análise detalhada` e `Conferência` materializada com preservação de período, lente, origem e contexto relevante do gráfico ao sair da home.
- Páginas de `Visão Geral`, `Análise detalhada`, `Conferência`, `Central operacional`, listas operacionais, detalhes e login migradas para a nova linguagem visual do admin, mantendo as rotas públicas atuais.
- Formulário de upload de fatura centralizado na tela de faturas do admin.
- Deduplicação forte implementada em OFX e faturas.

### Ainda não implementado

Esta lista cobre capacidades que ainda não existem no produto ou que ainda não entraram em operação de forma funcional.

- Conciliação automática de faturas.
- Vínculo automático ou definitivo com pagamento de conta além da conciliação manual assistida.
- Dashboard completo de fluxo de caixa como visão separada.
- Gráficos dedicados de evolução por categoria usando a visão de consumo.
- Migração ampla de toda a análise histórica para base conciliada além do já necessário para a leitura atual.

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

- `PAGAMENTO EFETUADO` dentro da própria fatura não é a fonte oficial da conciliação.
- `DESCONTO NA FATURA` entra como componente técnico de quitação do tipo `invoice_credit`.
- A quitação da fatura é composta por `bank_payment` e `invoice_credit`.
- Status válidos de conciliação:
  - `pending_review`
  - `partially_conciliated`
  - `conciliated`
  - `conflict`
- Regras de cardinalidade:
  - um pagamento bancário conciliado não pode ser usado em duas faturas diferentes;
  - uma fatura pode acumular mais de um `bank_payment`;
  - itens `invoice_credit` são derivados automaticamente dos créditos da própria fatura.
- Regras de candidatos do extrato:
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
- Regras determinísticas usam `source_scope`:
  - `bank_statement`
  - `credit_card_invoice_item`
  - `both`
- Um item `charge` de fatura só pode terminar com categoria existente na base oficial ou com a categoria oficial de não categorizado.
- Se fallback ou regra devolver categoria inexistente, o item cai no não categorizado oficial.

## 5. Estrutura Analítica e Operação Atual

### Leitura analítica atual

- O admin separa a leitura em três entradas analíticas complementares:
  - **Resumo:** entrada principal, com alternância entre `Visão de Caixa` e `Visão de Competência`, barra de contexto própria, faixa inicial de cards por lente, gráfico principal com controle temporal local, comparativo compacto de categorias apenas na lente de competência, resumo executivo, alertas mais urgentes e CTAs contextuais por bloco.
  - **Análise detalhada:** aprofundamento da visão de consumo, com breadcrumb `Resumo > Análise detalhada`, retorno ao resumo com contexto restaurado, breakdown categorial completo, comparações históricas, gráficos analíticos atuais, alertas e ações.
  - **Conferência:** visão bruta, cobertura da leitura principal, sinais auxiliares de conciliação, itens técnicos e HTML renderizado para auditoria, também com breadcrumb próprio e retorno ao resumo com contexto restaurado.
- Essa reorganização é uma decisão explícita de arquitetura da informação do produto, feita antes da próxima etapa de gráficos dedicados por categoria.
- A `Visão de Caixa` da home usa a leitura de caixa do mês-base para fluxo líquido, entradas, saídas e maior saída individual do período.
- A `Visão de Competência` da home usa a leitura gerencial já suportada pelo produto para resultado do mês, receitas por competência, despesas por competência e margem do mês.
- O gráfico principal da home acompanha a lente ativa, usa barras para entradas/saídas ou receitas/despesas e linha para fluxo/resultado, e mantém o controle temporal local ao próprio bloco.
- A barra de contexto do topo das telas analíticas separa explicitamente:
  - breadcrumb e orientação de navegação;
  - controles globais da página;
  - chips de contexto ativo ou de origem;
  - foco contextual leve quando a navegação veio da home.
- Os controles globais do `Resumo` passam a explicitar que `Visão de Caixa` e `Visão de Competência` são controles da página inteira, enquanto `Ano`, `Últimos 12 meses`, dropdown de ano e abas de comparação continuam locais ao bloco do gráfico principal.
- O resumo executivo principal e os alertas prioritários acompanham a lente ativa sem misturar caixa com competência de forma artificial.
- A home passa a funcionar como hub de aprofundamento: cards, gráfico, alertas, categorias e conferência oferecem CTAs explícitos com preservação de estado por querystring.
- O breakdown mensal por categoria do mês-base usa a visão de consumo:
  - transações válidas da conta por `transaction_date`;
  - itens `charge` de faturas `conciliated` por `purchase_date`;
  - ajuste técnico separado para `credit` genérico, pela `purchase_date` do próprio item quando disponível e sem redistribuição entre categorias;
  - exclusão de `payment` da própria fatura e de `bank_payment` conciliado do consumo.
- As comparações históricas por categoria usam a mesma visão de consumo no mês-base, no mês anterior e no mesmo mês do ano anterior quando houver base suficiente.
- Alertas e ações recomendadas seguem a mesma separação:
  - sinais ligados a consumo, categorias, concentração e variação usam a visão de consumo;
  - sinais gerais de saldo e cobertura do período continuam ancorados no resumo principal conciliado quando isso fizer mais sentido.

### Operação admin atual

- **Análise**
  - ver resumo financeiro enxuto por período, com KPIs conciliados, resumo executivo, categorias prioritárias e alertas prioritários;
  - ver análise detalhada por período;
  - manter visão bruta, cobertura e sinais auxiliares em uma área de conferência separada;
  - disparar nova análise determinística manualmente.
- **Transações**
  - listar, filtrar e revisar transações;
  - editar categoria e tipo da transação;
  - criar ou atualizar regra manual a partir da revisão;
  - fazer reclassificação em lote com preview.
- **Regras e categorias**
  - criar, editar, ativar, desativar e excluir regras;
  - definir `kind_mode` e `source_scope`;
  - listar, criar e editar categorias da base oficial.
- **Faturas**
  - importar CSV Itaú;
  - listar faturas importadas e ver detalhe da fatura;
  - ver itens, tipo técnico e categoria quando aplicável;
  - editar manualmente a categoria de item `charge` com preview e confirmação explícita;
  - aplicar a categoria na base com preview dos itens impactados, confirmação, criação/atualização de regra e reaplicação dos itens elegíveis existentes.
- **Conciliação**
  - visualizar candidatos de pagamento;
  - vincular manualmente pagamentos do extrato;
  - desfazer vínculo;
  - acompanhar status e componentes da conciliação.

### Pontos ainda não consolidados

Esta lista cobre capacidades que já existem, mas ainda dependem de maturação, refinamento visual ou restrições operacionais para entregar todo o valor esperado.

- Gráficos dedicados de evolução por categoria na visão de consumo ainda não foram promovidos.
- A visão de fluxo de caixa ainda não foi materializada como dashboard próprio.
- A decisão de conciliação ainda é manual.
- A visão de consumo por categoria ainda depende de faturas totalmente conciliadas.

## 6. Riscos e Limitações Conhecidas

- O baixo valor analítico percebido da leitura principal ainda não foi resolvido; a base ficou mais confiável, mas o painel principal ainda precisa de refinamento de produto.
- A leitura mensal e as comparações históricas por categoria já usam a visão de consumo, mas os gráficos dedicados dessa evolução ainda não foram promovidos.
- O resumo principal conciliado e a visão de consumo já foram separados em páginas mais claras dentro da nova shell, mas a semântica da `Visão de Competência` ainda precisa amadurecer, especialmente do lado das receitas.
- A visão bruta ainda é necessária para auditoria.
- O MVP continua dependente do layout oficial de OFX Itaú e CSV Itaú já suportados.

## 7. Roadmap do Produto

### Estado atual do trabalho

- **Estado atual do ciclo:** `REFINAMENTO_EM_ANDAMENTO`
- **Tema ativo:** evolução da home para painel principal orientado à decisão, com **Visão de Caixa** como leitura padrão e **Visão de Competência** como leitura alternável.
- **Épico ativo:** `Home visual de fluxo de caixa`
- **Histórias em refino:** próximo recorte funcional da home e da camada analítica ainda não materializado, já partindo da barra contextual e da navegação contextual entregues entre `Resumo`, `Análise detalhada` e `Conferência`.
- **Fatia ativa ou candidata:** próximo recorte do épico ainda em refinamento, agora já partindo da barra de contexto padronizada e da navegação contextual materializadas entre `Resumo`, `Análise detalhada` e `Conferência`.
- **Próxima ação esperada:** retomar o refinamento do próximo recorte do épico `Home visual de fluxo de caixa`, já apoiado na home como hub de aprofundamento e sem fechar antecipadamente qual será a próxima fatia candidata.
- **Motivo resumido:** a camada analítica agora já preserva melhor período, lente e contexto ao navegar entre `Resumo`, `Análise detalhada` e `Conferência`; com isso, o foco volta para definir com mais precisão qual incremento funcional analítico vem na sequência.
- **Prompt canônico para iniciar o ciclo:** usar `docs/pm_cycle_start_prompt.md` para classificar o estado atual antes de decidir entre refinamento, documentação ou handoff técnico.
- **Documento operacional da frente de readequação:** usar `docs/admin_readequacao_control.md` para acompanhar a readequacao global do admin em fases, sem perder a coesao entre shell, IA, responsividade e checkpoints de execucao.
- **Checkpoint atual da frente de readequação:** a Fase 1 da branch dedicada já consolidou shell global, sidebar, topbar e contracts base de page header; a Fase 2 já readequou a `Visão Geral`, reforçando a hierarquia da home e o bloco inferior de continuidade com dados reais do mês-base; a Fase 3 já reorganizou `Análise detalhada` e `Conferência` com cards de contexto mais fortes, navegação rápida por seções e painéis mais próximos do ritmo visual do template original; a Fase 4 já migrou `Central operacional`, `Lançamentos`, `Faturas`, `Reaplicar regras`, `Regras` e `Categorias` para um archetype mais estável de operação e configuração; a Fase 5 já alinhou detalhes, edição contextual e login à mesma linguagem do admin; a próxima etapa operacional registrada no documento de controle é a Fase 6, focada no acabamento responsivo, na consolidação final e na validação da branch inteira.

### Como ler o roadmap

- **Ordem:** posição atual do tema na fila de evolução do produto.
- **Prioridade:** importância relativa do tema dentro do roadmap atual.
  - `P0`: tema crítico no horizonte atual.
  - `P1`: tema importante na sequência.
  - `P2`: tema relevante, mas posterior.
- **Refino:** decisão explícita do PM sobre necessidade de refinamento de produto antes de execução.
- **Status:** situação atual do tema no roadmap.
  - `ativo em refinamento`: tema já eleito como frente ativa do roadmap, com direção revisada e refinamento em andamento antes do handoff técnico.
  - `próximo tema para refinamento`: item mais imediato da fila que ainda precisa passar por refino antes de virar execução.
  - `futuro priorizado`: item importante no horizonte atual, mas ainda dependente de ordem, refinamento ou encaixe com outros temas.
  - `pronto para execução`: item com direção já suficiente e dependências principais atendidas.
  - `futuro planejado`: item previsto no roadmap, mas fora da faixa imediata de execução.
  - `futuro`: item reconhecido, porém mais distante e ainda dependente de definições relevantes.
  - `concluído`: item já entregue e absorvido pelo estado atual do produto.

### Frentes de evolução

- **Leitura financeira e visualização**
  - transformar a leitura principal do produto em algo que gere valor real em poucos segundos;
  - concentrar painel principal, comparações por fonte, modos de leitura e futuros gráficos dedicados.
- **Operação nativa na aplicação**
  - reduzir dependência de fluxos externos para ingestão e operação recorrente;
  - incluir importação de extrato pela própria aplicação e futura unificação do controle de faturas hoje mantido em outro projeto.
- **Planejamento financeiro e evolução**
  - levar o produto do controle histórico para gestão ativa;
  - incluir planejamento financeiro, acompanhamento de evolução e alertas financeiros.
- **Experiência, estética e clareza**
  - tratar revisão estética como frente transversal de produto, e não tema cosmético isolado;
  - reduzir excesso de texto, melhorar hierarquia visual e aumentar a capacidade de extrair valor rápido da análise.

### Tema ativo do roadmap

- **Tema ativo:** evolução da home para painel principal orientado à decisão, com **Visão de Caixa** como leitura padrão e **Visão de Competência** como leitura alternável.
- **Referência no backlog:** corresponde à **Ordem 1** do backlog estratégico.
- **Status:** ativo em refinamento.
- **Decisão consolidada:** a home deve evoluir para uma entrada mais visual e mais orientada à decisão, com **Visão de Caixa** como leitura padrão e **Visão de Competência** como leitura alternável.
- **Observação:** este bloco é apenas um recorte operacional da Ordem 1 e não uma segunda estrutura paralela de prioridade.

### Estrutura de refinamento do tema ativo

- **Hierarquia correta de refinamento:** tema ou iniciativa do roadmap -> épicos -> histórias de usuário -> fatias prontas para execução.
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
  4. Como usuário, quero alternar entre Visão de Caixa e Visão de Competência na home para mudar a lente principal sem sair da entrada do sistema.
  5. Como usuário, quero atalhos claros para `Análise detalhada` e `Conferência` quando precisar aprofundar ou auditar a leitura principal.
- **Observação de produto:** revisão estética caminha junto com esse épico e não como trilha cosmética isolada posterior.

##### Primeira fatia definida: faixa inicial de 4 cards mensais

- **Observação de evolução:** esta definição inicial foi posteriormente absorvida pela alternância entre `Visão de Caixa` e `Visão de Competência`; a home continua começando com uma faixa de quatro cards, mas a composição atual por lente está registrada na quarta fatia implementada abaixo.
- **Objetivo da fatia:** materializar visualmente a semântica financeira já existente do sistema, sem introduzir nova lógica de domínio.
- **Modo padrão da home nesta fatia:** `Visão de Caixa`, materializando a leitura de fluxo de caixa já existente.
- **Escopo inicial:** a primeira implementação da home deve exibir uma faixa inicial com 4 cards mensais:
  1. **Fluxo líquido do mês**
  2. **Entradas do mês**
  3. **Saídas do mês**
  4. **Consumo do mês**
- **Definição dos cards:**
  - **Fluxo líquido do mês:** `entradas realizadas no mês - saídas realizadas no mês`; é o principal KPI da home e deve responder rapidamente como o caixa do mês está se comportando.
  - **Entradas do mês:** soma de todas as entradas realizadas no período; serve para dar contexto ao fluxo líquido.
  - **Saídas do mês:** soma de todas as saídas realizadas no período; serve para dar contexto ao fluxo líquido.
  - **Consumo do mês:** total de consumo do período na visão de consumo; não deve duplicar pagamento de fatura como consumo e existe para separar leitura de consumo da leitura de liquidação de caixa.
- **Comparação padrão dos cards:** cada card deve exibir o valor do mês atual, a variação absoluta contra o mês anterior e a variação percentual contra o mês anterior, quando aplicável.
- **Regra de semântica:** esta fatia não cria semântica nova; ela apenas materializa visualmente a semântica já consolidada do sistema em visão conciliada, separação entre fluxo de caixa e consumo e leitura financeira baseada nas transações já processadas.
- **O que não entra nesta fatia:** disponível até o fim do mês, projeção de fechamento, próximas obrigações, recorrências, top categorias na home principal, patrimônio, metas, investimentos, nova lógica de conciliação, alteração da semântica de consumo e alteração da semântica de pagamento de fatura.
- **Decisão de UX da primeira fatia:** a primeira faixa da home deve priorizar leitura rápida e baixo ruído; a intenção não é construir um dashboard completo neste momento, mas sim uma entrada visual clara para o estado financeiro mensal.
- **Critério de prontidão para implementação:** esta fatia estará pronta quando os 4 cards estiverem assumidos como bloco inicial da home, o modo padrão estiver definido como `Visão de Caixa`, a comparação contra o mês anterior estiver assumida como padrão dos cards e estiver explícito que não haverá forecast nem recorrência nesta primeira entrega.

##### Segunda fatia implementada: gráfico principal de evolução anual em fluxo de caixa

- **Objetivo da fatia:** ampliar a capacidade de leitura rápida da home com uma visão temporal clara da evolução do ano, mantendo a home orientada à decisão sem introduzir nova lógica de domínio.
- **Fonte de verdade da fatia:** a mesma visão de **fluxo de caixa** já usada na faixa inicial da home para fluxo líquido, entradas e saídas.
- **Escopo inicial:** a home deve exibir um gráfico principal anual com 12 meses do **ano calendário selecionado**, de **janeiro a dezembro**, incluindo meses zerados.
- **Séries do gráfico:**
  - **Fluxo líquido mensal** em **linha**
  - **Entradas mensais** em **barras**
  - **Saídas mensais** em **barras**
- **Convenção numérica do gráfico:**
  - entradas devem ser exibidas **acima de zero**;
  - saídas devem ser exibidas **abaixo de zero**;
  - fluxo líquido pode assumir valores positivos ou negativos e cruzar a linha de zero.
- **Cobertura temporal:** o gráfico deve sempre exibir os 12 meses do ano calendário selecionado, mesmo quando algum mês não tiver movimentação, caso em que o valor do mês deve aparecer como zero.
- **Regra de semântica:** esta fatia **não cria semântica nova**; ela apenas materializa visualmente a visão de fluxo de caixa já consolidada na home.
- **O que não entra nesta fatia:**
  - visão de consumo no mesmo gráfico;
  - forecast;
  - comparação por fonte (`Extrato`, `Fatura`, `Conciliado`);
  - alternância entre `Visão de Caixa` e `Visão de Competência` dentro do gráfico;
  - drill-down;
  - múltiplos gráficos adicionais no mesmo PR.
- **Estado após implementação:** o gráfico fica materializado na home como bloco principal logo após a faixa inicial, usa ano calendário fechado, mantém meses zerados visíveis, usa barras para entradas e saídas e linha para fluxo líquido, e preserva a separação semântica entre fluxo de caixa e consumo.

##### Terceira fatia implementada: comparativo visual das categorias do mês na home

- **Objetivo da fatia:** ampliar a leitura gerencial da home com um bloco-resumo que destaque, de forma rápida e comparável, onde o consumo do mês mais pesou em relação ao mês anterior, sem transformar a home em uma análise categorial completa.
- **Fonte de verdade da fatia:** a mesma visão de **consumo** já consolidada no produto para leitura por categorias.
- **Escopo materializado:** a home passa a exibir um bloco-resumo com as **Top 5 categorias de consumo do mês-base**, ordenadas pelo maior gasto do mês atual.
- **Referência histórica padrão:** **mês anterior**.
- **Formato visual do bloco:** **lista/ranking compacto**, com uma linha principal por categoria.
- **Conteúdo de cada linha:** nome da categoria, valor do mês atual, valor do mês anterior, variação absoluta e variação percentual quando houver base comparável.
- **Regra para categoria sem base no mês anterior:** o valor do mês anterior aparece como **R$ 0,00**, a categoria recebe a marcação **“nova no mês”** e não há tentativa de forçar percentual artificial ou infinito.
- **Regra de semântica:** esta fatia **não cria semântica nova**; ela apenas materializa visualmente a visão de consumo já utilizada na leitura categorial do produto.
- **O que não entra nesta fatia:** todas as categorias do mês na home, gráfico categorial pesado neste bloco, comparação contra o mesmo mês do ano anterior, mistura com visão de fluxo de caixa, tela completa de categorias no mesmo PR e drill-down a partir da home.
- **Estado após implementação:** a home mantém caráter de **resumo**, mostra apenas as Top 5 categorias com comparação contra o mês anterior e deixa a visão completa de categorias explicitamente para a análise detalhada ou para fatia futura específica.

##### Quarta fatia implementada: alternância entre Visão de Caixa e Visão de Competência na home

- **Objetivo da fatia:** transformar a home em uma entrada realmente orientada à decisão, separando com clareza a leitura de caixa da leitura por competência sem exigir que o usuário saia da home para trocar a lente principal.
- **Nomenclatura de interface consolidada:** a home passa a usar `Visão de Caixa` e `Visão de Competência` como rótulos oficiais da alternância principal.
- **Semântica geral:** esta fatia não cria motor contábil novo; ela materializa visualmente duas lentes gerenciais sobre dados já disponíveis no produto.
- **Escopo materializado:**
  - tabs curtas no topo da home para alternar entre `Visão de Caixa` e `Visão de Competência`;
  - quatro cards específicos por lente;
  - gráfico principal acompanhando a lente ativa;
  - controle temporal local do gráfico com `Ano` e `Últimos 12 meses`;
  - dropdown próprio de ano no modo `Ano`;
  - abas curtas de comparação visual por métrica, com série comparativa em linha mais leve/pontilhada;
  - bloco Top 5 categorias visível apenas na `Visão de Competência`;
  - resumo executivo e alertas prioritários acompanhando a lente ativa sem refatoração ampla do motor analítico.
- **Cards materializados por lente:**
  - **Visão de Caixa:** `Fluxo líquido do mês`, `Entradas do mês`, `Saídas do mês` e `Maior saída do mês`.
  - **Visão de Competência:** `Resultado do mês`, `Receitas por competência`, `Despesas por competência` e `Margem do mês`.
- **Regra do gráfico nesta fatia:** o controle temporal afeta apenas o gráfico principal; o restante da home continua mensal, ancorado no mês-base da página.
- **Estrutura visual atual do gráfico por lente:**
  - **Visão de Caixa:** `Entradas` e `Saídas` em barras, com `Fluxo líquido` em linha.
  - **Visão de Competência:** `Receitas` e `Despesas` em barras, com `Resultado` em linha.
- **Regra do Top 5 categorias:** o ranking compacto continua usando a visão de consumo já consolidada, mas fica oculto na `Visão de Caixa` e aparece apenas na `Visão de Competência`.
- **O que continua fora desta fatia:** tela completa de categorias, drill-down novo a partir da home, comparação por fonte (`Extrato`, `Fatura`, `Conciliado`), dashboard separado de fluxo de caixa, novo motor contábil e refatoração ampla do sistema de alertas.
- **Estado após implementação:** a home passa a ter `Visão de Caixa` como padrão inicial, `Visão de Competência` como leitura alternável, cards coerentes por lente, gráfico principal com controle temporal local e comparação enxuta por abas, mantendo a home como **resumo** e não como análise completa.

##### Quinta fatia implementada: barra de contexto e navegação contextual entre Resumo, Análise detalhada e Conferência

- **Objetivo da fatia:** deixar mais claro onde o usuário está, o que está controlando e como aprofundar a leitura sem perder período, lente nem contexto de origem.
- **Escopo materializado:**
  - barra de contexto padronizada no topo de `Resumo`, `Análise detalhada` e `Conferência`;
  - separação explícita entre breadcrumb/navegação, controles globais da página e chips de contexto atual;
  - `Visão de Caixa` e `Visão de Competência` promovidas visualmente como controles globais do `Resumo`;
  - preservação de `selection_mode`, período, lente ativa, origem e contexto relevante do gráfico via querystring ao navegar entre as telas analíticas;
  - botão `Voltar ao resumo` restaurando o estado relevante na `Análise detalhada` e na `Conferência`;
  - CTAs contextuais por bloco da home para cards, gráfico, categorias, alertas e conferência;
  - foco contextual leve na tela de destino por banner superior e âncoras simples, sem drill-down pesado.
- **Regra de semântica:** esta fatia não reescreve a semântica da análise; ela melhora arquitetura de navegação, clareza contextual e continuidade de leitura entre telas já existentes.
- **Separação consolidada de controles:**
  - `Visão de Caixa` / `Visão de Competência` passam a ficar claramente posicionadas como controle global do `Resumo`;
  - `Ano`, `Últimos 12 meses`, dropdown de ano e abas de comparação continuam locais ao bloco do gráfico principal.
- **O que continua fora desta fatia:** clique direto nas séries do gráfico para drill-down, nova página dedicada de categorias, redesign amplo da análise detalhada, novo dashboard de fluxo de caixa, comparação por fonte e nova engine analítica.
- **Estado após implementação:** a home deixa de depender de atalhos genéricos e passa a funcionar como hub de aprofundamento contextual, enquanto `Análise detalhada` e `Conferência` passam a preservar melhor o contexto de origem sem perder seus papéis atuais.

### Backlog estratégico ordenado

#### Ordem 1 - Home orientada à decisão com Visão de Caixa como leitura padrão

- **Frente:** Leitura financeira e visualização
- **Objetivo de valor:** transformar a home na entrada principal do sistema, com leitura visual e valor real em poucos segundos.
- **Prioridade:** P0
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** precisa fechar estrutura da home, hierarquia da informação, KPIs, leitura padrão em `Visão de Caixa`, alternância com `Visão de Competência`, comparação mensal/anual e distribuição dos blocos.
- **Dependências:** base atual de consumo já estabilizada.
- **Status:** ativo em refinamento.

#### Ordem 2 - Revisão estética da aplicação

- **Frente:** Experiência, estética e clareza
- **Objetivo de valor:** reduzir excesso de texto, melhorar hierarquia visual e aumentar clareza de leitura.
- **Prioridade:** P0
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** precisa definir direção visual, padrões de cards, tabelas, gráficos e contraste entre informação principal e apoio como camada transversal da leitura principal.
- **Dependências:** deve caminhar junto com a evolução do painel principal, e não como trilha estética isolada posterior.
- **Status:** futuro priorizado.

#### Ordem 3 - Visão mensal e anual por Extrato / Fatura / Conciliado

- **Frente:** Leitura financeira e visualização
- **Objetivo de valor:** permitir leitura comparativa útil por fonte.
- **Prioridade:** P0
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** precisa fechar como essas fontes entram na navegação, nos controles e na leitura principal.
- **Dependências:** painel principal orientado à decisão.
- **Status:** futuro priorizado.

#### Ordem 4 - Modos Bruto / Categorias + filtros essenciais

- **Frente:** Leitura financeira e visualização
- **Objetivo de valor:** dar flexibilidade analítica sem exagerar na complexidade da interface.
- **Prioridade:** P0
- **Refino de produto necessário?:** Não
- **Motivo do refino:** já há direção suficiente.
- **Dependências:** refinamento do painel principal.
- **Status:** pronto para execução após refinamento da camada principal.
- **Observação:** os filtros essenciais devem priorizar categoria, conta/cartão e tipo básico quando necessário.

#### Ordem 5 - Importação de extrato pela aplicação

- **Frente:** Operação nativa na aplicação
- **Objetivo de valor:** reduzir dependência do Make para a operação principal.
- **Prioridade:** P1
- **Refino de produto necessário?:** Não
- **Motivo do refino:** escopo relativamente claro.
- **Dependências:** fluxo admin/upload.
- **Status:** futuro planejado.

#### Ordem 6 - Incorporar o controle de faturas hoje mantido em outro projeto

- **Frente:** Operação nativa na aplicação
- **Objetivo de valor:** unificar operação financeira relevante em um único produto.
- **Prioridade:** P1
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** precisa mapear o que realmente deve migrar, o que já existe e o que não faz sentido trazer.
- **Dependências:** levantamento funcional do projeto paralelo.
- **Status:** futuro planejado.

#### Ordem 7 - Planejamento financeiro

- **Frente:** Planejamento financeiro e evolução
- **Objetivo de valor:** evoluir do controle histórico para gestão ativa.
- **Prioridade:** P2
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** precisa definir escopo inicial, entidades e horizonte de planejamento.
- **Dependências:** painel analítico principal confiável.
- **Status:** futuro.

#### Ordem 8 - Acompanhamento de evolução financeira

- **Frente:** Planejamento financeiro e evolução
- **Objetivo de valor:** mostrar progresso financeiro ao longo do tempo.
- **Prioridade:** P2
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** depende da definição das métricas e do modelo de progresso.
- **Dependências:** planejamento financeiro + métricas definidas.
- **Status:** futuro.

#### Ordem 9 - Alertas financeiros e acompanhamento preventivo

- **Frente:** Planejamento financeiro e evolução
- **Objetivo de valor:** gerar alertas úteis, acionáveis e preventivos.
- **Prioridade:** P2
- **Refino de produto necessário?:** Sim
- **Motivo do refino:** depende da definição de métricas, thresholds e ações.
- **Dependências:** planejamento financeiro + acompanhamento de evolução.
- **Status:** futuro.

### Regra de governança do roadmap

- Todo tema do roadmap deve ter ordem e prioridade explícitas.
- A necessidade de refino é uma decisão explícita do PM e deve ficar registrada no roadmap.
- Tema com **Refino de produto necessário? = Sim** não deve virar prompt de implementação direta.
- Antes de execução técnica, esse tema precisa passar por refinamento de produto.
- Tema com **Refino de produto necessário? = Não** só pode virar execução quando as dependências estiverem atendidas e a ordem do backlog continuar fazendo sentido.
- O roadmap é a referência principal para direção futura do produto; o tema ativo deve ser sempre derivado dele, e não de uma segunda estrutura paralela de priorização.

### Próximo passo recomendado

- Retomar o refinamento do próximo recorte do épico `Home visual de fluxo de caixa`, agora já com barra de contexto padronizada e navegação contextual materializadas, sem cristalizar neste momento qual das histórias remanescentes será a próxima fatia candidata.

### Fora de escopo imediato desta frente

- empacotar múltiplas novas fatias da home no mesmo PR antes de refinar o próximo recorte do épico;
- alterar templates, rotas, serviços ou lógica do produto antes do refinamento virar fatia pronta;
- discutir design visual final em nível de detalhe além do necessário para fechar direção de produto;
- dashboard completo de fluxo de caixa;
- novo motor analítico;
- mudanças de domínio financeiro já estabilizado;
- conciliação automática;
- reestruturação ampla dos serviços além do necessário para a navegação e a camada visual analítica.
