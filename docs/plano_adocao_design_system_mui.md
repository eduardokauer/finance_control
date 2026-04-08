# Plano: Adocao do Design System MUI for Figma

## Objetivo

Aplicar o design system referenciado no arquivo publico do Figma baseado em `MUI for Figma v7.2.0` na aplicacao, com foco em:

- consistencia visual
- padronizacao de componentes
- base reutilizavel para as telas do admin
- alinhamento entre design e implementacao
- menor custo de manutencao visual ao longo do tempo

## Premissa principal

O projeto atual nao usa React nem a biblioteca `@mui/material`. A stack do admin hoje e:

- FastAPI
- Jinja2
- HTMX
- CSS customizada

Portanto, a recomendacao nao e "migrar a aplicacao inteira para MUI React". A recomendacao e:

- adotar o design system como sistema visual e de componentes
- portar os tokens e contratos de interface para a stack atual
- opcionalmente deixar a porta aberta para usar componentes React no futuro em areas especificas

## Referencias utilizadas

### Fonte principal

- arquivo publico do Figma informado pelo usuario:
  - `MUI for Figma v7.2.0 - Material UI - Standard`

### Fontes oficiais MUI

- Material UI for Figma
- Design resources
- Theming
- CSS theme variables

Pontos relevantes das fontes oficiais:

- o kit usa terminologia compartilhada com a biblioteca React
- o design kit foi pensado para aproximar props, tokens e componentes do codigo
- a estrategia oficial moderna do MUI gira em torno de tema, tokens e CSS variables

### Benchmark de mercado

- GitHub Primer:
  - separa fundamentos, tokens e componentes
  - forte disciplina de componentes reutilizaveis
- Atlassian Design System:
  - page headers, data tables e states bem padronizados
  - clareza entre layout, navegacao, componentes e estados
- Material UI:
  - sistema de tema claro
  - boa cobertura de estados, superficies, inputs e tabelas

## Diagnostico do estado atual

Hoje o admin ja passou por uma readequacao visual importante, mas ainda apresenta:

- tokens dispersos em CSS grande de `base.html`
- componentes de pagina e cards com variacoes manuais
- tabelas semelhantes com contratos proximos, mas ainda nao unificados de forma sistemica
- inconsistencia residual de densidade, espacamento, alturas, headers e acoes
- pouca separacao formal entre:
  - foundations
  - primitives
  - components
  - page patterns

## Leitura critica do pedido

Aplicar o design system nao deve significar:

- copiar visualmente o Figma tela a tela
- reescrever tudo para React/MUI agora
- fazer pixel-perfect sem adaptar ao dominio

Aplicar o design system deve significar:

- traduzir o kit para tokens reais do projeto
- construir uma biblioteca de componentes/admin patterns
- usar essa base para as telas existentes e futuras

## Decisao recomendada

Adotar o MUI for Figma em 4 camadas:

1. Foundations
2. Tokens
3. Component library do admin
4. Page templates/patterns

## O que nao entra neste plano

Para manter o esforco realista, este plano nao parte destas premissas:

- reescrever a app para React
- importar `@mui/material` no backend server-rendered como estrategia principal
- fazer migracao visual big bang
- perseguir equivalencia absoluta com cada detalhe do Figma

O objetivo e adotar o sistema, nao copiar uma tela.

## Escopo alvo

### Foundations

- cor
- tipografia
- espacamento
- radius
- elevacao
- shadows
- states
- motion minima
- iconografia

### Componentes base

- buttons
- icon buttons
- text fields
- selects
- search/autocomplete
- checkboxes/radios/switches
- chips/badges
- tabs
- cards/surfaces
- tables
- menus/dropdowns
- dialogs
- accordions
- tooltips
- toast/feedback
- empty states

### Page patterns

- page header minimalista
- toolbar de filtros
- KPI cards
- chart section
- operational table
- side actions / batch actions
- detail page
- technical page

## Mapeamento recomendado entre Figma e implementacao

### Figma -> codigo

- design tokens -> CSS variables
- componentes Figma -> macros Jinja / partials / classes semanticas
- page templates -> archetypes de pagina do admin
- variants/states -> modifiers CSS e atributos HTML

### Nomenclatura recomendada

- Figma/MUI:
  - `primary`, `secondary`, `error`, `warning`, `success`, `info`
- codigo:
  - manter a semantica equivalente, mas prefixada no sistema local
  - exemplo:
    - `--fc-color-primary-main`
    - `--fc-color-success-main`
    - `--fc-shadow-level-1`

### Regra de traducao

Quando o componente do Figma nao couber exatamente na stack atual:

1. preservar hierarquia e comportamento
2. preservar tokens e estados
3. adaptar a implementacao HTML/CSS/HTMX
4. evitar simular comportamento complexo sem necessidade real

## Estrategia de adocao

### Nao migrar para MUI React agora

Motivos:

- custo alto de reescrita
- stack atual entrega valor com server-side rendering
- HTMX se encaixa melhor no fluxo operacional atual
- o maior ganho imediato vem de consistencia visual, nao de trocar framework

### Criar um "MUI-inspired admin kit"

Isso significa:

- usar o Figma como fonte de verdade visual
- mapear tokens para CSS variables do projeto
- construir macros Jinja + classes CSS baseadas nesses tokens
- padronizar componentes do admin com contratos claros

## Plano de implementacao detalhado

### Fase 0 - Leitura e inventario do Figma

Objetivo:

- entender o kit antes de codificar qualquer componente

Passos:

1. Catalogar os componentes do arquivo do Figma realmente relevantes para o admin.
2. Extrair o inventario de:
   - cores
   - tipografia
   - espacamento
   - radius
   - elevation
   - states
3. Mapear equivalencias com o que ja existe no admin.
4. Identificar o que vem pronto no arquivo publico e o que pode depender da versao full do kit.
5. Registrar o gap entre:
   - o kit MUI
   - a linguagem atual do admin
   - necessidades reais do produto

Entregaveis:

- inventario de tokens
- inventario de componentes
- mapa de gaps

Esforco:

- 2 a 4 dias

### Fase 1 - Tokens e foundations

Objetivo:

- transformar o design system em base tecnica reutilizavel

Passos:

1. Criar taxonomia de tokens:
   - `--fc-color-*`
   - `--fc-space-*`
   - `--fc-radius-*`
   - `--fc-shadow-*`
   - `--fc-font-*`
   - `--fc-z-*`
2. Mapear tokens semanticos:
   - surface
   - surface-muted
   - border
   - text-primary
   - text-secondary
   - primary
   - success
   - warning
   - danger
3. Definir escala tipografica.
4. Definir grid de espacamento.
5. Definir escala de densidade para tabelas e formularios.
6. Mover o maximo possivel dos valores hardcoded para tokens.
7. Criar documentacao curta do token set.
8. Definir semanticamente o que e:
   - token de fundacao
   - token semantico
   - token de componente
9. Definir qual parte ficara em:
   - `:root`
   - tema base do admin
   - overrides locais raros

Entregaveis:

- token layer funcional
- base CSS padronizada

Esforco:

- 3 a 5 dias

### Fase 2 - Biblioteca de componentes

Objetivo:

- criar uma camada de componentes que traduza o Figma para a stack atual

Passos:

1. Criar primitives HTML/CSS/Jinja para:
   - buttons
   - inputs
   - selects
   - chips
   - badges
   - cards
   - accordions
   - tooltips
2. Criar componentes estruturais:
   - `page_header`
   - `filter_toolbar`
   - `metric_card`
   - `section_card`
   - `data_table`
   - `empty_state`
   - `action_menu`
3. Padronizar variantes e estados:
   - default
   - hover
   - focus
   - selected
   - disabled
   - loading
   - danger
4. Definir quando um componente e:
   - macro Jinja
   - partial
   - HTML livre com classes utilitarias
5. Definir contrato minimo de API visual por componente:
   - props aceitas
   - variantes
   - estados
   - slots opcionais
6. Criar versoes referencia para:
   - desktop
   - tablet
   - mobile

Entregaveis:

- admin kit reutilizavel

Esforco:

- 1 a 2 semanas

### Fase 3 - Tabelas, filtros e componentes de alta criticidade

Objetivo:

- atacar o coracao operacional do sistema

Passos:

1. Redesenhar o contrato visual das tabelas:
   - header
   - sorting
   - filter row quando necessario
   - selection
   - row actions
   - status badges
2. Redesenhar toolbars de filtro para:
   - densidade menor
   - hierarquia melhor
   - inputs consistentes
3. Criar padrao para action menus e acoes inline.
4. Criar padrao de listagem mobile/tablet.
5. Revisar overlays:
   - dropdowns
   - dialogs
   - anchored panels
6. Revisar componentes de dados e decisao inspirados no benchmark:
   - page header minimal
   - filter toolbar compacta
   - data table com densidade controlada
   - empty state sem excesso de texto
   - menu de acoes com iconografia consistente

Entregaveis:

- contratos visuais das listas operacionais

Esforco:

- 1 a 2 semanas

### Fase 4 - Rollout por familia de telas

Objetivo:

- aplicar o design system sem quebrar a operacao

Sequencia recomendada:

1. shell global e layout base
2. tabelas operacionais
3. visoes analiticas
4. configuracao
5. detalhes
6. telas tecnicas

Passos:

1. Substituir estilos locais por componentes do kit.
2. Remover duplicacoes de CSS.
3. Revisar headers, blocos e espacos.
4. Revisar responsividade.
5. Revisar densidade visual.
6. Revisar tooltips e textos auxiliares para manter o principio de pagina clean.

### Familias de tela recomendadas no rollout

- familia `overview`
  - dashboard
  - visoes principais
- familia `list`
  - lancamentos
  - faturas
  - regras
  - categorias
- familia `detail`
  - detalhe de lancamento
  - detalhe de fatura
- familia `technical`
  - telas tecnicas e de auditoria

Entregaveis:

- telas convergindo para a mesma familia visual

Esforco:

- 2 a 3 semanas

### Fase 5 - Documentacao e governanca

Objetivo:

- evitar que a aplicacao volte a divergir

Passos:

1. Criar documento de uso do design system no repo.
2. Definir regras para:
   - criar componente novo
   - estender variante
   - quando nao usar o padrao
3. Criar checklist de PR visual.
4. Criar catalogo simples de componentes no proprio repo.

Entregaveis:

- governanca minima do design system

Esforco:

- 2 a 4 dias

## Esforco total estimado

Para 1 engenheiro com apoio eventual de design:

- inventario e tokens: 1 a 2 semanas
- componentizacao: 2 a 3 semanas
- rollout de telas: 2 a 4 semanas
- consolidacao: 1 semana

Estimativa total:

- 6 a 10 semanas

## Impacto esperado

### Alto impacto de produto

- admin mais coerente
- menor fadiga visual
- melhor previsibilidade das interacoes
- ganho de velocidade para evoluir telas novas

### Alto impacto de engenharia

- reduz CSS ad hoc
- aumenta reuso
- reduz custo de manutencao visual
- cria base para futuras features sem redesenho local

### Medio impacto operacional

- exige rollout cuidadoso
- pode tocar muitas telas
- precisa de disciplina de regressao visual

## Artefatos recomendados no repo

Para que a adocao seja duravel, o trabalho deveria gerar pelo menos:

- arquivo de tokens do admin
- partials/macros compartilhadas para componentes base
- guia de uso curto em `docs/`
- checklist de PR visual
- mapa de componentes do admin

Arquivos candidatos:

- `app/templates/admin/partials/page_parts.html`
- `app/templates/admin/partials/*`
- camada CSS compartilhada fora de `base.html` quando fizer sentido
- documento de governanca em `docs/`

## Estrategia de QA

- validacao visual em desktop, tablet e mobile
- revisao de densidade em tabelas com dados reais
- revisao de acessibilidade:
  - foco
  - contraste
  - estados hover/focus/disabled
- smoke visual das 4 telas principais
- revisao de sobreposicao em:
  - dropdown
  - menu
  - modal
  - tooltip

## Riscos

- tentar portar o MUI literalmente para uma stack que nao e React
- ficar preso em ajuste pixel-perfect em vez de sistema
- subestimar o trabalho de tabelas densas
- criar tokens sem semantica e voltar a usar valores hardcoded

## Mitigacoes

- adotar "MUI as source of design language", nao "MUI React rewrite"
- priorizar foundations e componentes reutilizaveis
- atacar primeiro os componentes de maior recorrencia
- documentar a camada de tokens

## Ponto critico sobre o arquivo do Figma

A documentacao oficial do MUI indica diferenca entre versao community e full:

- community:
  - pode ter menor cobertura de customizacao
  - pode nao trazer a mesma riqueza de variables
- full:
  - inclui mais componentes e variables

Como o link informado e publico, a premissa deste plano e:

- o arquivo publico sera usado como referencia visual primaria
- se ele nao expuser as variables necessarias, os tokens serao inferidos do kit e consolidados no codigo

Esse ponto precisa ser validado no inicio da execucao.

## Criterios de aceite

- existe uma camada clara de tokens do admin
- os componentes recorrentes usam contratos comuns
- visoes principais compartilham a mesma linguagem
- tabelas e filtros seguem o mesmo padrao
- textos, tooltips, densidade e hierarquia visual ficam consistentes
- fica facil construir tela nova sem reabrir discussao visual do zero

## Sequenciamento recomendado

1. Tokens
2. Buttons/inputs/cards/chips
3. Tables/toolbars/menus
4. Shell global
5. Principais telas do admin
6. Detalhes e periferia

## Decisoes em aberto para revisar depois

- se vale criar um CSS utilitario leve ou seguir apenas com classes semanticas
- se algum trecho futuro merece islands React
- se o tema precisa nascer com dark mode ou apenas light mode primeiro
- se a densidade de tabela deve ter variante compacta e confortavel

## Recomendacao final

O caminho de maior retorno nao e trocar a stack para React/MUI agora. O caminho certo e aplicar o design system do MUI/Figma como base de tokens, componentes e page patterns na stack atual. Isso entrega o ganho visual e sistemico esperado com muito menos risco arquitetural.
