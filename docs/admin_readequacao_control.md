# Admin Readequacao Control

## Papel do arquivo

Este arquivo registra a frente de readequacao do admin so no nivel que ainda importa para leitura futura. Nao e um historico de execucao nem um espelho do plano completo.

`docs/project_context.md` continua sendo o contexto tecnico estavel do projeto.

## Fonte de referencia

- `docs/project_context.md`
- `docs/coder_workflow.md`
- template original do dashboard enviado pelo usuario como referencia visual e estrutural

## Objetivo da frente

Readequar o admin para uma linguagem visual e de navegacao consistente, sem mudar semantica de dominio.

## Arquitetura de informacao

### Estado atual

- `Visão Geral` -> `/admin`
- `Gráficos analíticos` -> `/admin/analysis/charts`
- `Lançamentos analíticos` -> `/admin/analysis/transactions`
- `Conferência` -> `/admin/conference`

### Alvo da camada analítica

- uma tela única de gráficos autônoma
- uma tela única de listagem autônoma

### Operacao

- `Central operacional` -> `/admin/operations`
- `Lancamentos` -> `/admin/transactions`
- `Faturas` -> `/admin/credit-card-invoices`
- `Reaplicar regras` -> `/admin/reapply`

### Configuracao

- `Regras` -> `/admin/rules`
- `Categorias` -> `/admin/categories`

### Contextuais

- login
- detalhe de lancamento
- detalhe de fatura
- edicao pontual de categoria de item de fatura
- fragments HTMX

## Direção da camada analítica

- as duas telas analíticas são canônicas e independentes
- a navegação entre gráficos e lançamentos é explícita
- `/admin/analysis` permanece como alias de compatibilidade para a tela de gráficos

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
- paineis de apoio
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

## Criterios de aceite

- nenhuma semantica de dominio muda por causa do redesign
- nenhuma pagina atual fica sem lugar claro na navegacao
- a home continua sendo resumo
- analise detalhada continua sendo profundidade
- conferencia continua sendo auditoria
- operacao e configuracao continuam acessiveis com baixo atrito
- layout funciona em desktop, tablet e mobile
