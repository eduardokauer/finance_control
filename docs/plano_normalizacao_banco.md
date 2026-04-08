# Plano: Normalizacao do Banco de Dados

## Objetivo

Normalizar o banco do sistema de forma segura, incremental e compativel com producao, aumentando:

- integridade referencial
- consistencia de leitura
- facilidade de evolucao
- auditabilidade
- seguranca de migracoes futuras

## Objetivo pratico

O foco nao e perseguir normalizacao teorica maxima. O foco e corrigir os pontos onde a modelagem atual gera:

- duplicacao de semantica
- risco de divergencia
- backfills manuais
- filtros inconsistentes
- acoplamento forte a strings livres

## Estado atual relevante

O modelo atual ja possui algumas entidades normalizadas:

- `categories`
- `source_files`
- `credit_cards`
- `credit_card_invoices`
- `credit_card_invoice_conciliations`

Mas ainda existem campos importantes denormalizados:

- `transactions.category` guarda string
- `credit_card_invoice_items.category` guarda string
- `categorization_rules.category_name` guarda string
- `transaction_audit_logs.previous_category/new_category` guardam string

Outras duplicacoes que precisam de analise:

- `credit_card_invoices` guarda `card_id` e tambem `issuer` / `card_final`
- `transactions` guarda `categorization_rule_id` e tambem `applied_rule`
- varios estados de dominio sao strings livres em vez de enums/constraints

## Diagnostico do problema

Hoje a base mistura tres tipos de dado:

1. dado mestre
2. snapshot historico
3. estado operacional

O maior problema e quando o sistema usa string como se fosse dado mestre.

Exemplo:

- categoria e entidade de dominio
- mas as tabelas principais armazenam o nome da categoria como texto
- isso facilita drift, alias legados, problemas de acento e operacoes de consolidacao mais custosas

## Benchmark e referencia de mercado

### Referencias utilizadas

- PostgreSQL:
  - uso de primary keys e foreign keys como base de integridade
- Supabase:
  - branching, `db pull`, `db diff`, `db reset`, migrations em Git
- Prisma:
  - expand-and-contract migrations
- PlanetScale:
  - backward compatible database changes
  - expand, migrate, contract

### Leitura de mercado aplicada

Os principais times de produto nao fazem renome ou refactor de schema grande em producao como "big bang". O padrao de mercado e:

1. expandir schema
2. backfillar dados
3. colocar dual read / dual write quando necessario
4. migrar aplicacao gradualmente
5. contrair schema antigo so depois de estabilizar

Esse plano segue exatamente essa linha.

## Principios do plano

1. Primeiro normalizar o que e mestre e editavel.
2. Preservar snapshots historicos quando eles fazem sentido de auditoria.
3. Nao quebrar leituras existentes no meio da migracao.
4. Toda mudanca estrutural deve ser backward compatible ate o cutover.
5. Toda migracao precisa ser testada fora da producao antes.

## Escopo recomendado de normalizacao

### Prioridade alta

- referencias de categoria
- referencias de regra
- constraints de estados de dominio mais estaveis

### Prioridade media

- contas/refs bancarias como entidade propria
- padronizacao de enums/check constraints
- entidades auxiliares de classificacao

### Prioridade baixa / opcional

- merchant normalization
- taxonomias auxiliares
- decomposicao adicional de snapshots historicos

## O que nao deve ser normalizado agora

Para manter o escopo correto, a recomendacao e nao atacar neste primeiro ciclo:

- analise persistida em `analysis_runs.payload`
- HTML gerado em `analysis_runs.html_output`
- snapshots historicos cujo valor maior e auditoria
- qualquer tentativa de remodelar conciliacao inteira no mesmo movimento

O primeiro ciclo deve priorizar integridade operacional, nao reescrita geral do dominio.

## Tabela de decisao por entidade

### `categories`

- manter como tabela mestre
- reforcar como fonte unica para referencia de categoria

### `categorization_rules`

- normalizar para `category_id`
- manter `pattern`, `kind_mode`, `source_scope` como campos operacionais

### `transactions`

- adicionar `category_id`
- avaliar `account_id` depois
- manter snapshots operacionais que apoiam auditoria

### `credit_card_invoice_items`

- adicionar `category_id`
- manter `description_raw`, `description_normalized` e campos de parcela

### `transaction_audit_logs`

- manter texto como snapshot
- adicionar FKs opcionais apenas se trouxer ganho analitico real

### `credit_card_invoices`

- manter `card_id`
- manter `issuer` e `card_final` como snapshot no primeiro momento

## Modelo alvo recomendado

### 1. Categorias como referencia real

Adicionar:

- `transactions.category_id -> categories.id`
- `credit_card_invoice_items.category_id -> categories.id`
- `categorization_rules.category_id -> categories.id`

Manter temporariamente:

- colunas string antigas para compatibilidade

Direcao final:

- leitura e escrita passam a usar `category_id`
- strings antigas sao removidas ou mantidas apenas como snapshot quando justificadas

### 2. Regras apontando para categoria por FK

Substituir semanticamente:

- `categorization_rules.category_name`

Por:

- `categorization_rules.category_id`

Motivo:

- evita drift apos rename/consolidacao de categoria

### 3. Logs de auditoria

Aqui a recomendacao e mista.

Manter como snapshot textual:

- `previous_category`
- `new_category`

Opcionalmente adicionar:

- `previous_category_id`
- `new_category_id`

Motivo:

- logs precisam sobreviver mesmo se a categoria for desativada, consolidada ou removida

### 4. Estados de dominio

Avaliar migracao de strings livres para:

- enums Postgres para dominios muito estaveis
- check constraints para dominios estaveis mas simples
- tabelas de referencia apenas quando houver valor real de negocio

Candidatos:

- `transaction_kind`
- `direction`
- `source_type`
- `import_status`
- `conciliation.status`
- `credit_card_invoice_conciliation_items.item_type`

Recomendacao pragmatica:

- comecar com check constraints ou enums apenas nos dominios pequenos e estaveis
- evitar lookup table para tudo

### 5. Entidades de conta

Hoje `transactions.account_ref` e string livre. A longo prazo, o modelo pode evoluir para:

- `accounts`
- `transactions.account_id`

Mas isso nao deve entrar na primeira fase se o objetivo principal for resolver integridade e consolidacao de categoria.

### 6. Snapshots que provavelmente devem permanecer

Nem toda duplicacao e erro.

Recomendacao de manter como snapshot:

- `credit_card_invoices.issuer`
- `credit_card_invoices.card_final`
- `transactions.applied_rule`

Motivo:

- auditoria
- leitura historica
- resiliencia operacional

Esses campos podem coexistir com FKs sem problema.

## Estrategia de migracao

### Expand -> Migrate -> Contract

Este plano deve ser seguido em todas as mudancas de schema com impacto em producao.

1. Expand

- adicionar novas colunas, FKs, indices e constraints frouxas

2. Migrate

- backfillar dados
- ajustar leitura/escrita da aplicacao
- monitorar inconsistencias

3. Contract

- remover colunas antigas apenas quando nao houver mais leitura/escrita nelas

## Plano detalhado por fases

### Fase 0 - Preparacao de ambiente e governanca

Objetivo:

- reduzir risco operacional antes de tocar no schema

Passos:

1. Confirmar que a historia de migrations no repo representa o estado remoto do Supabase.
2. Se houver drift remoto, executar processo de sincronizacao:
   - `supabase db pull`
   - repair da migration history se necessario
3. Definir ambiente seguro para ensaio:
   - branch Supabase
   - staging local com dump anonimo ou seed minimo
4. Definir checklist de migracao:
   - backup
   - dry run
   - validacao
   - rollback
5. Definir estrategia de observabilidade dos backfills.

Entregaveis:

- baseline confiavel do schema
- ritual de migracao documentado

Esforco:

- 2 a 4 dias

### Fase 1 - Normalizacao de categorias

Objetivo:

- resolver o principal problema de consistencia do sistema

Passos:

1. Adicionar `category_id` em `transactions`.
2. Adicionar `category_id` em `credit_card_invoice_items`.
3. Adicionar `category_id` em `categorization_rules`.
4. Criar indices para essas novas colunas.
5. Backfillar `category_id` por join com `categories.name`.
6. Identificar aliases e lixo legado:
   - acentos
   - variacoes de casing
   - nomes antigos
7. Criar tabela/estrutura temporaria de mapa de aliases se necessario.
8. Garantir que a categoria oficial `Nao Categorizado` tenha tratamento explicito.
9. Atualizar a aplicacao para dual read:
   - preferir `category_id`
   - cair para string enquanto a migracao estiver aberta
10. Atualizar a aplicacao para dual write:
   - gravar `category_id`
   - manter string antiga temporariamente
11. Adicionar verificacoes de integridade:
   - linhas sem categoria resolvida
   - regras sem categoria valida
   - invoice items com alias legado
12. Criar relatorio de divergencia antes do cutover.

Entregaveis:

- categorias referenciadas por FK nas tabelas principais

Esforco:

- 1 a 2 semanas

### Fase 2 - Regras e fluxos administrativos

Objetivo:

- impedir que a normalizacao seja furada pela camada de operacao

Passos:

1. Atualizar servicos de categorizacao para trabalhar por `category_id`.
2. Atualizar CRUD de regras.
3. Atualizar CRUD de categorias.
4. Atualizar consolidacao/movimentacao de categorias.
5. Atualizar importadores e reaplicacao.
6. Revisar consultas analiticas que hoje filtram por nome.
7. Atualizar exports, tabelas e filtros do admin para ler por join/FK.
8. Revisar qualquer SQL operacional manual que ainda dependa de nome textual.

Entregaveis:

- operacao inteira coerente com o modelo novo

Esforco:

- 1 a 2 semanas

### Fase 3 - Auditoria e historico

Objetivo:

- preservar rastreabilidade sem contaminar o modelo principal

Passos:

1. Decidir se `transaction_audit_logs` tera FKs opcionais adicionais.
2. Se sim, adicionar:
   - `previous_category_id`
   - `new_category_id`
3. Manter os snapshots textuais.
4. Atualizar escritor de audit log.
5. Garantir leitura historica resiliente.

Entregaveis:

- log auditavel e semanticamente mais rico

Esforco:

- 3 a 5 dias

### Fase 4 - Estados de dominio

Objetivo:

- reduzir valores invalidos e strings livres em estados estaveis

Passos:

1. Inventariar todos os campos com dominio fechado.
2. Classificar cada campo entre:
   - enum Postgres
   - check constraint
   - manter string
3. Aplicar primeiro aos dominos mais seguros:
   - `direction`
   - `conciliation item_type`
   - `conciliation status`
4. Atualizar aplicacao e testes.
5. Validar se `transaction_kind` deve virar enum agora ou depois.
6. Definir regra de evolucao futura:
   - enum para dominio estavel
   - tabela mestre apenas para dominio gerenciavel pelo usuario

Entregaveis:

- dominios mais confiaveis

Esforco:

- 4 a 7 dias

### Fase 5 - Contas e referencias auxiliares

Objetivo:

- avaliar a segunda camada de normalizacao

Passos:

1. Mapear variacao real de `account_ref`.
2. Decidir se vale criar `accounts`.
3. Se fizer sentido:
   - criar tabela
   - backfillar
   - adicionar `account_id`
4. Avaliar outras referencias auxiliares:
   - merchants
   - source subtypes
   - taxonomias operacionais

Entregaveis:

- decisao clara sobre a segunda onda de normalizacao

Esforco:

- 1 a 2 semanas se implementado
- 2 a 3 dias se apenas diagnosticado

### Fase 6 - Contract e limpeza

Objetivo:

- remover a camada antiga com seguranca

Passos:

1. Monitorar por um ciclo completo de uso.
2. Confirmar que toda escrita ja usa as novas FKs.
3. Confirmar que consultas analiticas ja nao dependem das strings antigas.
4. Remover dual write.
5. Remover colunas antigas quando seguro.
6. Reindexar, revisar constraints e atualizar documentacao.

Entregaveis:

- schema consolidado

Esforco:

- 3 a 5 dias

## Esforco total estimado

Escopo essencial:

- Fase 0 a Fase 4

Estimativa:

- 4 a 7 semanas

Escopo ampliado com contas e referencias auxiliares:

- 6 a 10 semanas

## Impacto esperado

### Alto impacto positivo

- consolidacao de categorias deixa de depender de update textual em cascata
- filtros e analises ficam mais robustos
- reduz bugs de alias, acento e nome legado
- melhora integridade entre regras, extrato e fatura

### Medio impacto tecnico

- toca servicos centrais
- exige migracoes cuidadosas
- exige revisao de queries e testes

### Alto valor futuro

- facilita IA de sugestao
- facilita consolidacao de taxonomia
- reduz custo de futuras features analiticas

## Riscos

- drift entre schema remoto e migrations
- backfill incompleto por alias legado
- leituras antigas ainda dependentes do nome textual
- tentativa de normalizar demais em um unico ciclo

## Mitigacoes

- usar branch de banco e dry runs
- comecar por categorias
- manter dual read/dual write enquanto necessario
- tratar alias legado explicitamente
- executar em fases pequenas com observabilidade

## Criterios de aceite

- categorias principais referenciadas por FK nas tabelas operacionais
- regras deixam de depender de `category_name`
- aplicacao funciona sem depender de comparacao textual de categoria
- migracoes sao reproduziveis no repo
- rollback e conhecido
- producao nao sofre big bang migration

## Ferramentas e processo recomendados

- Supabase branching para validar schema change
- `supabase db pull` para sincronizar historia
- `supabase migration new` ou SQL manual versionado
- `supabase db reset` para ensaio local
- PR obrigatorio para schema
- backfills pequenos e observaveis

## Checklist de cutover recomendado

Antes do cutover:

- migrations aplicadas em ambiente de ensaio
- relatorio de divergencia zerado ou conhecido
- dual read ativo
- dual write ativo
- testes de regressao passando

Durante o cutover:

- aplicar migration expand
- executar backfill
- validar contagens e linhas sem FK
- habilitar leitura preferencial por FK

Depois do cutover:

- monitorar erros de escrita/leitura
- monitorar consultas analiticas
- monitorar operacoes de categoria e regra
- so planejar `contract` depois de estabilidade comprovada

## Estrategia de testes

- testes de migration em banco vazio
- testes de migration em banco com dados reais anonimizados
- testes de integridade referencial
- testes de service layer para CRUD de categoria/regra
- testes de regressao das principais visoes analiticas

## Decisoes em aberto para revisar depois

- se `transaction_kind` entra agora ou em segunda onda
- se `accounts` entra junto ou depois
- se `merchant normalization` faz sentido para o produto atual
- se audit log ganha FKs adicionais ou permanece apenas textual

## Recomendacao final

O melhor recorte para comecar e a normalizacao de categorias, porque ela ataca o principal problema atual de integridade do sistema com impacto direto em operacao, analise e manutencao. Depois disso, o restante da normalizacao deve seguir por ondas pequenas, sempre usando expand-migrate-contract e ambiente de branch no Supabase antes de tocar producao.
