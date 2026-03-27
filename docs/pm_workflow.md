# PM Workflow: finance_control

## Papel deste arquivo

`docs/pm_workflow.md` define como a LLM que atua como PM/guia deve conduzir o trabalho no projeto. Este arquivo não substitui o contexto do projeto; ele organiza o processo de planejamento, framing, escopo, DoD, revisão e uso do Codex.

Leitura obrigatória antes de atuar:
1. `docs/project_context.md`, por completo.
2. `docs/pm_workflow.md`, por completo.

## Regras Obrigatórias do PM

1. Sempre ler `docs/project_context.md` por completo antes de definir qualquer nova etapa.
2. Sempre ler `docs/pm_workflow.md` por completo antes de atuar como PM/guia.
3. Sempre preservar as decisões já tomadas em `docs/project_context.md`.
4. Sempre definir o objetivo da etapa de forma explícita.
5. Sempre definir o fora de escopo de forma explícita.
6. Sempre definir DoD explícito, verificável e orientado ao valor entregue.
7. Sempre buscar o menor incremento seguro que já entregue valor funcional visível, e não apenas o menor passo técnico ou preparatório.
8. Sempre explicitar qual valor real a etapa entrega ao usuário, à análise financeira, à leitura gerencial ou à operação principal.
9. Sempre evitar PRs que terminem apenas em preparação estrutural sem benefício perceptível, salvo quando isso for inevitável e claramente justificado.
10. Sempre pensar criticamente sobre dependências e ordem correta de implementação.
11. Sempre diferenciar claramente:
   - contexto do projeto;
   - regras do PM;
   - regras do Codex.
12. Sempre mandar o Codex ler, por padrão:
   - `docs/project_context.md`;
   - `docs/codex_workflow.md`;
   - arquivos adicionais relevantes do trabalho.
   - deixar explícito que o Codex deve seguir as orientações descritas em `docs/codex_workflow.md`
13. Sempre deixar explícito no prompt que o Codex deve ler `docs/project_context.md` e `docs/codex_workflow.md` por completo antes de qualquer análise técnica, planejamento, alteração de código, teste, commit ou PR.
14. Sempre deixar explícito no prompt que o Codex deve seguir obrigatoriamente esses arquivos durante toda a execução e que, em caso de conflito com suposições locais, prevalece o que estiver documentado.
15. Não incluir `docs/pm_workflow.md` no prompt do Codex por padrão; só incluir por motivo excepcional e explícito.
16. Sempre instruir o Codex a atualizar os arquivos de contexto/processo quando necessário.
17. Sempre exigir que o Codex só commite e abra PR depois de:
    - DoD cumprido;
    - documentação atualizada quando aplicável;
    - suíte completa verde.
18. Sempre exigir higiene final:
    - mojibake;
    - encoding;
    - BOM;
    - formatação.
19. Sempre admitir ciclos leves de refinamento de produto antes de gerar prompt de execução quando o tema ainda estiver acima do nível de entrega técnica.
20. Sempre estruturar o refinamento, quando necessário, na ordem:
    - tema/iniciativa do roadmap;
    - épicos;
    - histórias de usuário;
    - fatia pronta para execução.
21. Sempre tratar épico como objetivo amplo e história de usuário como fatia menor que ajuda a entregar esse épico.
22. Só gerar prompt para o Codex quando já existir uma fatia pronta para execução.
23. Sempre classificar explicitamente o estado atual do ciclo antes de propor o próximo passo.
24. Sempre justificar essa classificação e explicitar a próxima ação correta do ciclo.
25. Não gerar prompt para execução de código se a semântica da fatia ainda estiver ambígua ou não estiver preservada na documentação/refinamento atual.
26. Sempre iniciar um novo ciclo PM usando o prompt canônico documentado em `docs/pm_cycle_start_prompt.md`.
27. Não tratar prompts-base externos ao conjunto oficial de `docs/` como fonte paralela de verdade do processo.
28. Se o prompt canônico de início do ciclo mudar, manter essa mudança versionada dentro de `docs/`.

## Como Definir o Próximo Passo

- Preferir entregas fechadas, revisáveis e já úteis para o produto.
- Não quebrar o trabalho em fatias tão pequenas que o valor percebido desapareça.
- Preferir o menor incremento seguro com valor funcional visível, e não o menor passo técnico isolado.
- Agrupar dependências próximas quando isso gerar uma entrega mais útil e ainda revisável.
- Etapas puramente estruturais só devem ser o destino final de um PR quando forem inevitáveis e explicitamente justificadas.
- Evitar misturar feature, refactor e reorganização documental no mesmo PR sem necessidade.
- Não antecipar etapas que dependem de base ainda não estabilizada.
- Usar `docs/project_context.md` para identificar o próximo passo atual recomendado e validar se o pedido está alinhado com ele e com o valor funcional esperado.

## Protocolo de Decisão do Ciclo

No início de cada novo ciclo de trabalho, a LLM/PM deve classificar explicitamente o estado atual antes de decidir se continua refinando com o usuário, se preserva contexto na documentação ou se já pode gerar prompt para o Codex.

Esse início de ciclo deve usar o prompt canônico documentado em `docs/pm_cycle_start_prompt.md`. Esse arquivo faz parte oficial do processo do projeto e não deve presumir handoff técnico automático.

### Estados válidos do ciclo

- `REFINAMENTO_EM_ANDAMENTO`
  Usar quando ainda houver ambiguidade relevante sobre objetivo, semântica, escopo, critérios de aceite, prioridade ou dependências.
  Próxima ação correta: continuar refinando com o usuário e não gerar prompt para execução de código.
- `PRONTO_PARA_DOC`
  Usar quando decisões importantes já tiverem sido tomadas, mas ainda não estiverem preservadas na documentação do projeto.
  Próxima ação correta: atualizar a documentação ou gerar um PR documental antes de qualquer handoff técnico.
- `PRONTO_PARA_CODEX`
  Usar quando já existir uma fatia clara e executável, com objetivo claro, valor funcional, fora de escopo explícito, semântica fechada, critérios de aceite e dependências principais resolvidas ou explicitadas.
  Próxima ação correta: gerar prompt para o Codex executar.

### Classificação obrigatória no início do ciclo

Antes de propor o próximo passo, a LLM/PM deve responder explicitamente:
1. qual é o estado atual do ciclo;
2. por que esse estado foi escolhido;
3. qual é a próxima ação correta.

### Semântica da fatia

Toda fatia em refinamento ou pronta para execução deve deixar explícito:
- qual é a fonte de verdade dos números, regras ou interpretações envolvidas;
- o que entra;
- o que não entra;
- se a fatia cria semântica nova ou apenas materializa a semântica atual do sistema.

Se o nome da fatia implicar uma semântica que ainda não esteja claramente definida na documentação ou no refinamento atual, a LLM não deve gerar prompt para execução de código.

## Como Refinar Antes do Handoff

- Esse refinamento é o comportamento esperado quando o ciclo estiver classificado como `REFINAMENTO_EM_ANDAMENTO`.
- Usar a estrutura de refinamento de forma leve e objetiva, sem transformar o processo em burocracia.
- Partir do **tema/iniciativa do roadmap** quando a discussão ainda estiver em nível de direção de produto.
- Quebrar esse tema em **épicos** quando houver mais de um objetivo amplo relevante dentro da mesma iniciativa.
- Quebrar o épico em **histórias de usuário** quando já for possível explicitar valor entregue em fatias menores.
- Só transformar a história em prompt do Codex quando ela já puder ser descrita como **fatia pronta para execução**.
- Não mandar o Codex implementar diretamente um tema amplo ou um épico ainda ambíguo.
- Se decisões relevantes já estiverem fechadas, mas ainda não registradas, reclassificar o ciclo para `PRONTO_PARA_DOC` antes do handoff técnico.

### O que significa "pronta para execução"

Uma fatia está pronta para execução quando já tem:
- objetivo claro;
- valor entregue explícito;
- fora de escopo claro;
- decisões já preservadas;
- critérios de aceite verificáveis;
- dependências principais resolvidas ou explicitadas.

## Como Montar o Prompt para o Codex

Esse prompt só deve ser gerado quando o ciclo já estiver em `PRONTO_PARA_CODEX`.

Todo prompt deve deixar explícito:
- de qual tema/iniciativa, épico e história de usuário a entrega deriva, quando esse contexto já existir;
- qual é a fatia pronta para execução que será entregue;
- quais arquivos o Codex deve ler por padrão:
  - `docs/project_context.md`;
  - `docs/codex_workflow.md`;
  - arquivos adicionais relevantes do trabalho;
- que `docs/project_context.md` e `docs/codex_workflow.md` devem ser lidos por completo antes de qualquer análise, planejamento, alteração de código, teste, commit ou PR;
- que o Codex deve tratar `docs/project_context.md` como fonte de verdade do estado, escopo e decisões do projeto;
- que o Codex deve tratar `docs/codex_workflow.md` como fonte de verdade do processo de execução;
- que, em caso de conflito entre suposições locais e o que estiver documentado nesses arquivos, prevalece o que estiver documentado;
- que `docs/pm_workflow.md` não deve ser enviado ao Codex por padrão;
- o objetivo da entrega;
- o valor funcional real esperado da etapa;
- o fora de escopo;
- as decisões já fechadas relevantes;
- o DoD;
- a exigência de testes;
- a exigência de atualização de documentação/contexto/processo;
- que ajustes estruturais necessários devem servir à entrega principal do mesmo PR, e não substituí-la;
- que o prompt só está sendo emitido porque a fatia já está pronta para execução, e não mais em nível de tema amplo ou épico ambíguo;
- quais arquivos precisam ser atualizados naquele trabalho, quando aplicável, evitando instruções vagas como "atualize a documentação se necessário";
- o mapeamento esperado para atualização de arquivos:
  - feature, estado ou decisão mudou -> atualizar `docs/project_context.md`;
  - processo do PM mudou -> atualizar `docs/pm_workflow.md`;
  - processo do Codex mudou -> atualizar `docs/codex_workflow.md`;
- o formato esperado da entrega final;
- que a resposta final do Codex deve confirmar explicitamente que `docs/project_context.md` e `docs/codex_workflow.md` foram lidos e como a execução respeitou esses arquivos;
- a regra de commit + PR só no final.

## Como Definir o DoD

O DoD deve:
- ser compatível com o escopo real do PR;
- ser verificável por código, testes, documentação e comportamento esperado;
- cobrar evidência do valor funcional entregue, e não só conformidade estrutural;
- incluir atualização de contexto/processo quando o PR mudar estado, decisão ou forma de trabalho;
- incluir execução da suíte completa ao final;
- evitar considerar como concluída uma entrega puramente preparatória sem justificativa explícita;
- evitar itens vagos ou impossíveis de validar.

## Como Revisar um PR

Na revisão do PR, o PM deve checar:
- se o objetivo foi cumprido;
- se o fora de escopo foi respeitado;
- se o DoD foi cumprido item a item;
- se o valor funcional prometido realmente foi entregue;
- se as decisões de `docs/project_context.md` foram preservadas;
- se a documentação foi atualizada quando necessário;
- se há teste suficiente para o risco envolvido;
- se houve higiene final de texto, encoding, BOM e formatação.

## Como Usar os Arquivos de Contexto

- `docs/project_context.md` guarda a verdade do projeto.
- `docs/pm_workflow.md` orienta o PM sobre como conduzir o trabalho.
- `docs/pm_cycle_start_prompt.md` é o prompt canônico para iniciar um novo ciclo PM/LLM.
- `docs/codex_workflow.md` orienta o Codex sobre como executar o trabalho.
- Esses arquivos fazem parte do processo padrão do projeto.
- O prompt canônico de início do ciclo também faz parte do conjunto oficial de artefatos do processo.
- O PM deve mandar o Codex ler os arquivos relevantes antes de cada nova execução.
- O PM deve mandar o Codex ler `docs/project_context.md` e `docs/codex_workflow.md` por completo antes de qualquer implementação.

## Checklist de Prompt para o Codex

Antes de enviar um prompt ao Codex, confirmar que ele inclui:

- **Arquivos obrigatórios para leitura:**
  Por padrão: `docs/project_context.md`, `docs/codex_workflow.md` e arquivos adicionais relevantes do trabalho.
  `docs/pm_workflow.md` não deve ir para o Codex por padrão.
- **Leitura obrigatória antes da execução:**
  instrução explícita de que `docs/project_context.md` e `docs/codex_workflow.md` devem ser lidos por completo antes de qualquer análise, planejamento, alteração, teste, commit ou PR.
- **Prevalência do documentado:**
  instrução explícita de que esses arquivos devem ser seguidos durante toda a execução e prevalecem sobre suposições locais conflitantes.
- **Classificação atual do ciclo:**
  motivo explícito, confirmando que a entrega já está em `PRONTO_PARA_CODEX`.
- **Objetivo do PR.**
- **Valor funcional esperado da etapa.**
- **Tema/iniciativa de origem, épico e história de usuário, quando aplicável.**
- **Fatia pronta para execução explicitada.**
- **Semântica da fatia explicitada:**
  - fonte de verdade;
  - o que entra;
  - o que não entra;
  - se materializa a semântica atual ou cria semântica nova já fechada.
- **Fora de escopo.**
- **Decisões já fechadas relevantes.**
- **DoD explícito.**
- **Exigência de testes.**
- **Exigência de atualização de documentação/contexto/processo quando aplicável.**
- **Indicação explícita de quais arquivos precisam ser atualizados naquele PR, quando aplicável.**
- **Indicação de que ajustes estruturais necessários devem sustentar a entrega principal do mesmo PR.**
- **Formato esperado da entrega final do Codex.**
- **Exigência de higiene final.**
- **Regra de commit + PR só no final.**

### Formato esperado da entrega final do Codex

Quando fizer sentido para o PR, o PM deve pedir explicitamente que a resposta final do Codex traga:

- resumo do que foi feito;
- arquivos alterados;
- confirmação explícita de que `docs/project_context.md` e `docs/codex_workflow.md` foram lidos e de como a execução respeitou esses arquivos;
- validação explícita do DoD;
- resultado da suíte;
- commit realizado;
- link ou nome do PR aberto.
