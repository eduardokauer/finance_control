# Plano: Acoes Sem Refresh no Admin

## Objetivo

Eliminar refresh completo de pagina nas acoes operacionais do admin e migrar a experiencia para um fluxo de interacoes parciais, mantendo:

- stack atual baseada em FastAPI + Jinja2 + HTMX
- progressive enhancement
- URLs compartilhaveis nos filtros
- baixo risco de regressao
- rastreabilidade das acoes sensiveis

Este plano assume que o objetivo nao e transformar o admin em SPA. A direcao recomendada e manter renderizacao server-side com atualizacao parcial via HTMX.

## Estado atual

Hoje a aplicacao ja tem base parcial para isso:

- HTMX carregado globalmente em `app/templates/admin/base.html`
- acoes com preview parcial ja existem em:
  - `transactions.py`
  - `reapply.py`
  - `categories.py`
- parte importante do admin ainda usa `POST -> RedirectResponse(303)` e recarrega a pagina inteira
- filtros de pagina sao majoritariamente renderizados por GET e ainda nao estao padronizados para troca parcial do conteudo principal

Principais hotspots identificados no admin:

- `rules.py`
  - criar, editar, ativar/desativar, excluir regra
- `reapply.py`
  - aplicar reaplicacao ainda fecha em redirect
- `transactions.py`
  - atualizar lancamento
  - aplicar acoes em lote
- `invoices.py`
  - aplicar categoria de item
  - conciliar fatura
  - desfazer vinculacao
- `categories.py`
  - criar, editar, reatribuir e excluir categoria
- `dashboard.py`
  - uploads administrativos ainda fecham em redirect
- `auth.py`
  - login/logout podem continuar com redirect tradicional

## Benchmark e referencia de mercado

### Referencias oficiais e benchmark

- HTMX oficial:
  - `hx-boost` para transformar links e forms em AJAX com fallback nativo
  - `hx-target` para atualizar containers especificos
  - `hx-swap` para substituir fragmentos, linhas, cards e tabelas
- Stripe Dashboard:
  - listas com filtros persistentes
  - drilldown sem perder contexto
  - recarga parcial priorizando listas e paines, nao a pagina toda
- Atlassian Dynamic Table:
  - sorting, paginacao e interacoes em tabela como capacidade nativa do componente
- GitHub Primer:
  - overlays, autocomplete, action menus e filtros sobre listas densas

### Leitura de mercado aplicada ao projeto

Os principais players nao resolvem esse problema com refresh total da pagina em acoes frequentes de operacao. O padrao de mercado para apps operacionais server-driven hoje e:

- GET com URL canonica e filtros preservados
- POST/PUT/DELETE com retorno parcial para o trecho afetado
- feedback imediato via toast/status inline
- atualizacao local do card, tabela, badge ou resumo impactado
- refresh completo apenas em:
  - login/logout
  - upload com fluxo de navegacao
  - mudancas estruturais de pagina inteira

## Direcao recomendada

Adotar um modelo padronizado de interacao parcial com quatro regras:

1. Toda pagina operacional tera um `content root` identificavel.
2. Toda acao tera um `response contract` explicito:
   - atualizar linha
   - atualizar secao
   - atualizar resumo + tabela
   - emitir evento global
3. Filtros e ordenacao serao tratados como estado de URL e nao como estado escondido de formulario.
4. Operacoes sensiveis terao preview/confirmacao ou undo curto, nunca mutacao silenciosa.

## O que nao entra neste escopo

Para evitar diluicao do trabalho, este plano nao pressupoe:

- migracao para SPA
- WebSockets em tempo real
- reescrita completa da camada de templates
- undo universal em todas as mutacoes
- background jobs obrigatorios no primeiro recorte

## Matriz de prioridade por modulo

### Prioridade P0

- `transactions.py`
  - update de lancamento
  - filtros/ordenacao da listagem
  - bulk preview/apply
- `categories.py`
  - edicao inline
  - CRUD de categoria
  - reassign/delete
- `invoices.py`
  - aplicar categoria de item
  - conciliar/desvincular

### Prioridade P1

- `rules.py`
  - CRUD e toggle
- `reapply.py`
  - preview e apply sem refresh
- `analysis.py`
  - filtros e drilldowns preservando contexto sem reload estrutural

### Prioridade P2

- `dashboard.py`
  - uploads com feedback parcial
- `auth.py`
  - pode permanecer full page no primeiro ciclo

## Contrato de navegacao recomendado

Para filtros, ordenacao e drilldown, seguir a mesma regra em todas as paginas:

- URL e a fonte de verdade do estado navegavel
- HTMX atualiza o container principal
- `HX-Push-Url` sincroniza o navegador
- recarregar a URL diretamente deve reproduzir a mesma tela
- voltar/avancar do browser precisa preservar o estado da listagem

## Escopo funcional alvo

### Camada 1: sem refresh nas acoes pontuais

- editar lancamento
- editar item de fatura
- editar categoria inline
- criar/editar/ativar/excluir regra
- criar/editar categoria
- reatribuir categoria
- excluir categoria
- desfazer vinculacao de conciliacao

### Camada 2: sem refresh nas acoes compostas

- aplicar acoes em lote em lancamentos
- reaplicar regras
- conciliar faturas
- gerar previews
- aplicar filtros de listagem
- ordenar listagens

### Camada 3: sem refresh na navegacao intra-pagina

- troca de filtros nas visoes principais
- paginacao de tabelas
- drilldowns de cards e graficos
- troca de abas internas e acordeoes com URL preservada quando fizer sentido

## Arquitetura proposta

### 1. Contrato de pagina

Cada pagina administrativa passa a seguir este contrato:

- `page header`
- `toolbar/filters`
- `page summary`
- `primary list/table`
- `secondary panels` quando houver
- `toast region`

Cada um desses blocos precisa ter `id` estavel para receber swap parcial.

### 2. Contrato de resposta do backend

Em vez de `RedirectResponse` em quase toda mutacao, as rotas administrativas passam a suportar:

- modo pagina cheia
- modo fragmento HTMX

Padrao recomendado:

- request normal:
  - responde com redirect ou pagina completa
- request HTMX:
  - responde com fragmento e cabecalhos auxiliares

Cabecalhos/eventos sugeridos:

- `HX-Trigger` para toast global
- `HX-Trigger-After-Swap` para recarregar contadores/cards dependentes
- `HX-Push-Url` para filtros e ordenacao

### 3. Biblioteca de fragmentos

Criar uma camada clara de parciais reutilizaveis:

- linha de tabela
- bloco de resumo
- toolbar de filtros
- estado vazio
- preview panel
- toast/feedback
- dialog de confirmacao

Isso reduz divergencia e permite evolucao gradual.

### 3.1. Catalogo minimo de fragmentos

Fragmentos que valem nascer compartilhados:

- `table_shell`
- `table_body`
- `table_row`
- `toolbar_filters`
- `toolbar_summary`
- `inline_editor`
- `preview_panel`
- `toast_message`
- `empty_state`
- `confirm_dialog_body`

### 3.2. Estrategia de swap por tipo de elemento

- linha isolada:
  - `outerHTML` da linha
- tabela com filtros:
  - swap do container da tabela inteira
- KPI ou resumo:
  - swap do card/bloco
- preview:
  - swap do panel de preview
- erros de formulario:
  - swap do proprio form ou da regiao de erros

### 4. Estrategia por tipo de acao

#### Acoes de baixa criticidade

Exemplos:

- toggle de regra
- salvar categoria inline
- editar observacao

Padrao:

- `hx-post`
- atualizacao do proprio elemento ou da linha
- toast discreto

#### Acoes de media criticidade

Exemplos:

- editar lancamento
- editar item de fatura
- reatribuir categoria

Padrao:

- preview opcional ou confirmacao curta
- atualizacao da linha + KPIs dependentes
- log de auditoria preservado

#### Acoes de alta criticidade

Exemplos:

- bulk apply
- reaplicar regras
- conciliar fatura
- excluir categoria/regra

Padrao:

- preview obrigatorio quando houver impacto em massa
- confirmacao explicita
- retorno parcial da area afetada
- evento para refrescar:
  - totais
  - contadores
  - tabelas relacionadas

## Plano de implementacao detalhado

### Fase 0 - Inventario e padrao base

Objetivo:

- mapear todas as mutacoes e classifica-las por risco
- definir o contrato tecnico unico

Passos:

1. Inventariar rotas `POST` do admin.
2. Classificar cada rota:
   - inline
   - secao
   - tabela inteira
   - pagina inteira
3. Criar helper utilitario para detectar request HTMX.
4. Criar helper utilitario para respostas com `HX-Trigger`.
5. Definir padrao de naming de fragmentos.
6. Criar toast region global em `base.html`.
7. Criar guideline tecnica em `docs/` para futuras acoes.

Entregaveis:

- matriz de acoes
- helper de resposta HTMX
- toast/event bus minimo

Esforco:

- 2 a 3 dias

### Fase 1 - Acoes inline e de linha

Objetivo:

- remover refresh das acoes de linha mais frequentes

Passos:

1. Padronizar edicoes inline de categoria e campos operacionais.
2. Converter update de regra para retorno parcial.
3. Converter toggle/delete de regra.
4. Converter criar/editar categoria.
5. Converter reatribuir categoria.
6. Converter excluir categoria com refresh parcial da tabela e dos contadores.
7. Garantir foco e acessibilidade apos swap.

Entregaveis:

- CRUDs leves sem refresh
- feedback visual uniforme

Esforco:

- 4 a 6 dias

### Fase 2 - Formularios completos sem refresh

Objetivo:

- remover refresh das telas de detalhe e formularios completos

Passos:

1. Ajustar detalhe de lancamento para salvar no contexto atual.
2. Ajustar edicao de item de fatura.
3. Ajustar operacoes de conciliacao:
   - vincular
   - desfazer
   - recalcular status
4. Atualizar cards de resumo dependentes sem reload total.
5. Tratar erros de validacao inline.

Entregaveis:

- formularios com validacao e retorno parcial

Esforco:

- 4 a 7 dias

### Fase 3 - Filtros, ordenacao e paginacao sem refresh

Objetivo:

- transformar as listagens em telas exploraveis sem reload total

Passos:

1. Definir contrato unico de querystring para filtros.
2. Aplicar `hx-boost` ou equivalente server-driven na toolbar.
3. Fazer ordenacao por cabecalho atualizar apenas a lista alvo.
4. Fazer paginacao parcial.
5. Sincronizar URL com o estado atual.
6. Garantir deep link reproduzivel por URL.
7. Padronizar comportamento de busca:
   - submit explicito em filtros criticos
   - debounce curto apenas para busca textual quando o custo da query permitir
8. Garantir fallback sem JS:
   - o mesmo endpoint deve continuar servindo HTML completo por GET normal

Entregaveis:

- tabelas filtraveis e ordenaveis sem refresh

Esforco:

- 5 a 8 dias

### Fase 4 - Acoes em lote e previews pesados

Objetivo:

- atacar as mutacoes de maior risco mantendo experiencia fluida

Passos:

1. Padronizar preview de bulk.
2. Trocar apply final por resposta parcial com:
   - resumo de impacto
   - tabela atualizada
   - KPIs atualizados
3. Aplicar o mesmo padrao a reaplicacao de regras.
4. Adicionar estados:
   - processando
   - concluido
   - parcialmente concluido
   - erro
5. Definir quando usar background job futuro.

Entregaveis:

- bulk flows sem refresh
- contrato de previews reutilizavel

Esforco:

- 5 a 8 dias

### Fase 5 - Uploads, navegacao contextual e acabamento

Objetivo:

- reduzir os ultimos refreshs perceptiveis e consolidar a UX

Passos:

1. Revisar uploads para:
   - manter pagina atual
   - atualizar lista de cargas
   - atualizar feedback de analise disparada
2. Padronizar drilldowns preservando filtros.
3. Revisar loading states.
4. Revisar acessibilidade:
   - `aria-live`
   - foco apos swap
   - confirmacoes
5. Revisar observabilidade e logs.
6. Medir latencia percebida das principais acoes apos a migracao.
7. Revisar mensagens:
   - sucesso
   - erro
   - validacao
   - operacao em andamento

Entregaveis:

- experiencia sem refresh coesa ponta a ponta

Esforco:

- 3 a 5 dias

## Esforco total estimado

Cenario recomendado com 1 engenheiro principal:

- levantamento e fundacao: 1 semana
- conversao das acoes principais: 2 a 3 semanas
- filtros, tabelas e acoes em lote: 2 a 3 semanas
- acabamento e estabilizacao: 1 semana

Estimativa total:

- 5 a 8 semanas corridas

Se o escopo for fatiado pelo valor operacional primeiro:

- MVP de maior impacto: 2 a 3 semanas
- consolidacao completa: 5 a 8 semanas

## Impacto esperado

### Alto impacto

- reduz atrito operacional do admin
- acelera revisao de categorias, regras e conciliacoes
- melhora sensacao de produto profissional
- preserva contexto e reduz perda de foco

### Medio impacto tecnico

- exige refatoracao de varias rotas administrativas
- aumenta numero de fragmentos e contratos de UI
- exige disciplina de testes de fragmento e pagina cheia

### Baixo risco arquitetural

Porque reaproveita a stack atual:

- sem SPA
- sem reescrever frontend
- sem introduzir framework novo

## Riscos

- proliferacao de parciais sem padrao
- estados inconsistentes entre tabela e KPI
- regressao de acessibilidade apos swap
- formularios grandes com validacao parcial mal resolvida
- excesso de logica JS fora do HTMX

## Mitigacoes

- guideline unica de fragmentos
- refresh coordenado por eventos
- testes de rotas HTMX e paginas normais
- evitar JS custom quando HTMX resolver
- adotar componentes de toolbar/tabela compartilhados

## Criterios de aceite

- principais acoes operacionais nao recarregam a pagina inteira
- filtros e ordenacao atualizam apenas a area relevante
- URL continua refletindo o estado relevante da tela
- pagina funciona sem JS de forma degradada
- feedback de sucesso/erro e visivel
- KPIs e listas dependentes nao ficam inconsistentes

## Sequenciamento recomendado

1. Regras e categorias
2. Lancamentos e detalhes
3. Faturas e conciliacao
4. Filtros/ordenacao/paginacao
5. Bulk/reapply/uploads

## Dependencias

- consolidacao dos componentes compartilhados de tabela e toolbar
- convencao de IDs estaveis nas secoes
- cobertura de testes de UI e servico

## Estrategia de testes e validacao

### Testes tecnicos

- testes de rota para request normal
- testes de rota para request HTMX
- testes de regressao em filtros e ordenacao
- testes de permissao e CSRF/session quando aplicavel
- smoke tests de navegacao principal

### Testes de UX

- refresh perceptivel some nas acoes prioritarias
- foco apos salvar continua no contexto correto
- mensagens de erro nao desaparecem sem contexto
- voltar/avancar no navegador continua confiavel

### Metricas de acompanhamento

- quantidade de actions ainda com redirect total
- tempo medio das operacoes prioritarias
- quantidade de erros de swap/fragmento no frontend
- quantidade de chamados/bugs de contexto perdido

## Decisoes em aberto para revisar depois

- quais acoes devem ter undo real vs. apenas toast de sucesso
- se uploads devem virar assinc com polling
- se bulk apply muito grande deve ir para background job
- se filtros devem usar debounce em busca textual

## Recomendacao final

A melhor estrategia para este projeto e adotar um modelo "HTML over the wire" mais consistente, em vez de migrar para SPA. O sistema ja tem HTMX, Jinja e boa parte dos contratos de pagina. O ganho maior vira de padronizar respostas parciais, sincronizar URL/filtros e tratar feedback de operacao como primeira classe.
