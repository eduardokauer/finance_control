# Admin Readequacao Control

## Papel deste arquivo

`docs/admin_readequacao_control.md` controla a readequacao global do admin a partir do template original enviado pelo usuario. Ele existe para manter coesao entre shell, arquitetura de informacao, responsividade, prioridades de execucao e checkpoints da implementacao.

Este arquivo nao substitui `docs/project_context.md`. O contexto do projeto continua sendo a fonte de verdade do produto e das decisoes de dominio. Aqui fica a frente operacional desta readequacao, com fases, criterios de saida e acompanhamento da execucao.

## Fontes de referencia

- `docs/project_context.md`
- `docs/codex_workflow.md`
- template original do dashboard enviado pelo usuario como referencia visual e estrutural

## Regra de traducao do template

- usar o template original como fonte de direcao visual, hierarquia e linguagem de layout
- nao reutilizar o codigo do prototipo Next.js diretamente na stack atual
- preservar a arquitetura real do produto, suas rotas publicas e sua semantica de dominio
- adaptar a arquitetura de informacao para as telas reais do produto, sem copiar itens ficticios do mock

## Objetivo desta frente

Readequar o admin inteiro para a mesma visao do template original, corrigindo a adaptacao anterior e deixando o produto com:

- shell global mais coerente
- arquitetura de informacao mais clara
- paginas pertencendo a uma mesma familia visual
- melhor leitura em desktop, tablet e mobile
- home, analise, conferencia, operacao, configuracao e detalhes falando a mesma lingua visual

## Principios de execucao

- fazer a readequacao como uma frente unica, mas com ordem interna fechada
- preservar semantica de caixa, competencia, conferencia e operacao ja consolidadas
- usar ajustes estruturais para sustentar a entrega, sem transformar a frente em refactor abstrato
- priorizar contracts reutilizaveis de template e archetypes de pagina
- validar desktop, tablet e mobile durante a execucao, nao so no final
- atualizar este documento e `docs/project_context.md` a cada checkpoint relevante

## Arquitetura de informacao alvo

### Principal

- `Visao Geral` -> `/admin`
- `Analise detalhada` -> `/admin/analysis`
- `Conferencia` -> `/admin/conference`

### Operacao

- `Central operacional` -> `/admin/operations`
- `Lancamentos` -> `/admin/transactions`
- `Faturas` -> `/admin/credit-card-invoices`
- `Reaplicar regras` -> `/admin/reapply`

### Configuracao

- `Regras` -> `/admin/rules`
- `Categorias` -> `/admin/categories`

### Contextuais, sem item fixo de menu

- login
- detalhe de lancamento
- detalhe de fatura
- edicao pontual de categoria de item de fatura
- fragments HTMX

### Itens que nao devem virar menu fixo agora

- `Relatorios`
- `Importacao`
- `Contas Bancarias`
- `Cartoes de Credito`
- `Carteiras`
- `Ajuda`

## Archetypes alvo

### `overview`

- header forte
- faixa de KPIs
- bloco principal dominante
- coluna lateral de apoio
- blocos complementares abaixo

### `analysis`

- barra de contexto clara
- conteudo principal
- paines de apoio
- leitura progressiva

### `list`

- header
- toolbar contextual
- conteudo principal em card
- tabela forte no desktop
- cards/listas compactas no mobile

### `detail`

- breadcrumb/back
- cabecalho com status e acoes
- resumo principal
- blocos secundarios abaixo

### `auth`

- linguagem visual coerente com o admin
- experiencia simplificada, sem sidebar

## Criterios de aceite transversais

- nenhuma semantica de dominio muda por causa do redesign
- nenhuma pagina atual fica sem lugar claro na nova navegacao
- a home continua sendo resumo
- analise detalhada continua sendo profundidade
- conferencia continua sendo auditoria
- operacao e configuracao continuam acessiveis com baixo atrito
- layout funciona em desktop, tablet e mobile

## Plano por fases

### Fase 0 - Controle e alinhamento

- **Status:** concluida
- **Objetivo:** registrar a frente de readequacao, sua ordem de execucao e seus criterios de saida
- **Entregas desta fase:**
  - criar este documento
  - referenciar este documento em `docs/project_context.md`
  - registrar o status inicial da frente e a branch dedicada
- **Criterio de saida:** a frente fica documentada de forma autoexplicativa

### Fase 1 - Fundacao da shell e do sistema visual

- **Status:** concluida
- **Objetivo:** consolidar a fundacao visual que vai sustentar todas as telas seguintes
- **Escopo:**
  - revisar sidebar, topbar, espacos, superficies, tokens visuais e contracts internos
  - alinhar o shell atual mais fortemente com a hierarquia do template original
  - consolidar partials e contracts reutilizaveis para header, toolbar, section card, empty state e badges
  - revisar a base responsiva do shell para desktop, tablet e mobile
- **Arquivos provaveis:**
  - `app/templates/admin/base.html`
  - `app/templates/admin/partials/sidebar.html`
  - `app/templates/admin/partials/*.html`
  - `app/web/routes/admin/helpers.py`
- **Criterio de saida:**
  - shell mais proxima da visao do template original
  - contracts base definidos para as demais telas
  - nenhuma rota administrativa sem suporte coerente da nova shell

### Fase 2 - Readequacao da home

- **Status:** concluida
- **Objetivo:** fazer a `Visao Geral` parecer de fato a tela principal do produto
- **Escopo:**
  - reorganizar hierarquia da home
  - reforcar faixa de KPIs, grafico principal, alertas, resumo executivo, categorias e bloco de continuidade
  - melhorar o encaixe visual entre os blocos ja implementados
  - revisar layout mobile/tablet da home como parte da entrega
- **Dependencias:** Fase 1 concluida
- **Criterio de saida:** a home incorpora a visao do template original sem inventar semantica nova

### Fase 3 - Camada analitica

- **Status:** concluida
- **Objetivo:** alinhar `Analise detalhada` e `Conferencia` ao mesmo sistema visual e de hierarquia
- **Escopo:**
  - reorganizar topo, contexto, blocos principais e areas secundarias
  - tornar `Analise detalhada` uma extensao natural da home
  - tornar `Conferencia` uma pagina de auditoria clara e consistente com o novo admin
- **Dependencias:** Fases 1 e 2 concluidas
- **Criterio de saida:** ambas as telas ficam visualmente integradas ao admin e com melhor leitura progressiva

### Fase 4 - Operacao e configuracao

- **Status:** concluida
- **Objetivo:** migrar listas operacionais e telas de configuracao para archetypes coerentes
- **Escopo:**
  - `Central operacional`
  - `Lancamentos`
  - `Faturas`
  - `Reaplicar regras`
  - `Regras`
  - `Categorias`
- **Dependencias:** Fase 1 concluida
- **Criterio de saida:** listas, toolbars, filtros e cards mobile seguem um mesmo padrao estavel

### Fase 5 - Detalhes e fluxos contextuais

- **Status:** concluida
- **Objetivo:** alinhar detalhes e fluxos contextuais a nova linguagem
- **Escopo:**
  - detalhe de lancamento
  - detalhe de fatura
  - edicao de categoria de item de fatura
  - login
- **Dependencias:** Fases 1 e 4 concluidas
- **Criterio de saida:** detalhes deixam de parecer paginas tecnicas isoladas e passam a seguir o archetype de detalhe

### Fase 6 - Acabamento responsivo e consolidacao final

- **Status:** concluida
- **Objetivo:** fechar consistencia, responsividade e regressao visual antes da validacao final
- **Escopo:**
  - revisar desktop, tablet e mobile
  - ajustar drawers, tabelas, cards, estados vazios e densidade visual
  - reforcar smoke tests e checks de UI
  - atualizar `docs/project_context.md` com o estado consolidado da frente
- **Dependencias:** fases anteriores concluidas
- **Criterio de saida:** a readequacao fica consistente o suficiente para validacao final da branch inteira

## Regras de responsividade

### Desktop

- sidebar persistente
- topbar completa
- grids em 2 ou 3 colunas quando fizer sentido
- tabelas plenas

### Tablet

- sidebar em drawer
- topbar compacta
- grids reduzidos
- filtros podendo colapsar sem perder clareza

### Mobile

- drawer lateral
- coluna unica como padrao
- cards e paines reorganizados verticalmente
- tabelas convertidas para linhas/cards resumidos
- blocos laterais descendo para baixo do conteudo principal

## Regras de validacao

- quando a fase alterar apenas `docs/`, rodar `test-docs`
- quando a fase alterar qualquer arquivo fora de `docs/`, rodar a suite completa
- revisar encoding, BOM, mojibake e formatacao a cada checkpoint
- registrar neste documento o status da fase antes de seguir para a proxima

## Registro de progresso

### 2026-03-29

- branch de trabalho criada: `codex/admin-layout-readequation`
- template original reavaliado como referencia principal da visao do redesign
- plano completo por fases registrado neste documento
- `docs/project_context.md` referenciado para manter coesao
- Fase 1 concluida com revisao e readequacao da shell global, da sidebar, da topbar e dos contracts base de page header
- a base compartilhada do admin agora oferece fundacao mais forte para encaixar as proximas fases sem repetir estrutura em cada template
- checkpoint validado com `test-docs`, smoke/UI do admin e suite completa verde
- Fase 2 iniciada com reorganizacao concreta da `Visao Geral`
- a home passou a aproximar mais fortemente a hierarquia do template original: cards mais fortes, grafico principal com maior dominancia visual, coluna lateral de alertas mais clara, resumo executivo em grid, categorias com barra visual e bloco inferior de movimentacoes recentes
- o fechamento operacional da home agora usa dados reais do mes-base, sem criar tela nova nem semantica paralela
- checkpoint da Fase 2 validado com `test-docs`, suite focada da home e suite completa verde
- Fase 3 iniciada com reorganizacao estrutural de `Analise detalhada` e `Conferencia`
- a camada analitica passou a adotar cards de contexto mais fortes, navegacao rapida por secoes, hero cards de leitura e paines mais proximos do ritmo visual do template original
- checkpoint da Fase 3 validado com `test-docs`, smoke/UI do admin e suite completa verde
- Fase 4 concluida com migracao das telas de operacao e configuracao para um archetype mais estavel, com hero cards, metricas rapidas, formularios laterais, listas principais mais claras e continuidade mais proxima do template original
- `Central operacional`, `Lancamentos`, `Faturas`, `Reaplicar regras`, `Regras` e `Categorias` agora compartilham hierarquia mais consistente entre contexto, metricas, listas e acoes
- checkpoint da Fase 4 validado com `test-docs`, smoke/UI do admin e suite completa verde
- Fase 5 concluida com readequacao do detalhe de lancamento, do detalhe de fatura, da edicao contextual de categoria de item de fatura e do login
- os fluxos contextuais agora seguem a mesma linguagem do admin, com hero cards, guias de acao e melhor separacao entre resumo, manutencao pontual, preview e persistencia
- checkpoint da Fase 5 validado com `test-docs`, smoke/UI do admin e suite completa verde
- Fase 6 concluida com passe final de responsividade, utilitarios de layout, reducao de estilos inline e reforco dos contracts de layout dos archetypes do admin
- o mobile agora trata melhor tabs, chips e grupos de acoes em largura reduzida, enquanto a branch ficou mais consistente entre home, analise, conferencia, operacao, configuracao e detalhes
- checkpoint da Fase 6 validado com `test-docs`, smoke/UI do admin e suite completa verde
- estado operacional atual da branch: frente inteira consolidada e pronta para validacao integrada da branch pelo usuario

### 2026-04-03

- refinamento incremental do topo analitico iniciado a partir do feedback de uso da branch
- o seletor global de periodo foi compactado em uma barra inline com modo, campo ativo e resumo curto do periodo, reduzindo altura ocupada no topo do `Resumo`, da `Analise detalhada` e da `Conferencia`
- a mudanca preserva a separacao entre controle global da pagina e controles locais do grafico, mas reduz o peso visual e o espaco consumido pelo seletor de periodo

### 2026-04-04

- a frente entrou em um segundo passe estrutural a partir da insatisfacao com a adaptacao anterior da home
- a `Visao Geral` deixou de depender da alternancia por lente e passou a ser reorientada para uma overview neutra com:
  - filtros globais
  - blocos principais do mes
  - grafico de 12 meses conciliado
  - grafico de 12 meses de extrato
  - grafico de 12 meses de fatura
  - grafico de categorias
  - alertas com saida clicavel para listagens uteis
- a arquitetura de informacao principal da branch foi alinhada para:
  - `Visao Geral`
  - `Visao conciliada`
  - `Visao de Extrato`
  - `Visao de Faturas`
  - `Categorias`
- `Categorias` passou a evoluir para subhome analitica propria, com grafico principal, ranking clicavel, composicao filtrada da categoria e manutencao da taxonomia na mesma area
- `Visao conciliada`, `Visao de Extrato` e `Visao de Faturas` estao sendo reposicionadas como areas principais do menu, sem depender da antiga narrativa da home por lente
