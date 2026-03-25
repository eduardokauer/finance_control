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

## Como Definir o Próximo Passo

- Preferir entregas fechadas, revisáveis e já úteis para o produto.
- Não quebrar o trabalho em fatias tão pequenas que o valor percebido desapareça.
- Preferir o menor incremento seguro com valor funcional visível, e não o menor passo técnico isolado.
- Agrupar dependências próximas quando isso gerar uma entrega mais útil e ainda revisável.
- Etapas puramente estruturais só devem ser o destino final de um PR quando forem inevitáveis e explicitamente justificadas.
- Evitar misturar feature, refactor e reorganização documental no mesmo PR sem necessidade.
- Não antecipar etapas que dependem de base ainda não estabilizada.
- Usar `docs/project_context.md` para identificar o próximo passo atual recomendado e validar se o pedido está alinhado com ele e com o valor funcional esperado.

## Como Montar o Prompt para o Codex

Todo prompt deve deixar explícito:
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
- `docs/codex_workflow.md` orienta o Codex sobre como executar o trabalho.
- Os 3 arquivos fazem parte do processo padrão do projeto.
- O PM deve mandar o Codex ler os arquivos relevantes antes de cada nova execução.
- O PM deve mandar o Codex ler `docs/project_context.md` e `docs/codex_workflow.md` por completo antes de qualquer implementação.

## Checklist de Prompt para o Codex

Antes de enviar um prompt ao Codex, confirmar que ele inclui:

1. Arquivos obrigatórios para leitura.
   Por padrão: `docs/project_context.md`, `docs/codex_workflow.md` e arquivos adicionais relevantes do trabalho.
   `docs/pm_workflow.md` não deve ir para o Codex por padrão.
2. Instrução explícita de que `docs/project_context.md` e `docs/codex_workflow.md` devem ser lidos por completo antes de qualquer análise, planejamento, alteração, teste, commit ou PR.
3. Instrução explícita de que esses arquivos devem ser seguidos durante toda a execução e prevalecem sobre suposições locais conflitantes.
4. Objetivo do PR.
5. Valor funcional esperado da etapa.
6. Fora de escopo.
7. Decisões já fechadas relevantes.
8. DoD explícito.
9. Exigência de testes.
10. Exigência de atualização de documentação/contexto/processo quando aplicável.
11. Indicação explícita de quais arquivos precisam ser atualizados naquele PR, quando aplicável.
12. Indicação de que ajustes estruturais necessários devem sustentar a entrega principal do mesmo PR.
13. Formato esperado da entrega final do Codex.
14. Exigência de higiene final.
15. Regra de commit + PR só no final.

### Formato esperado da entrega final do Codex

Quando fizer sentido para o PR, o PM deve pedir explicitamente que a resposta final do Codex traga:

1. Resumo do que foi feito.
2. Arquivos alterados.
3. Confirmação explícita de que `docs/project_context.md` e `docs/codex_workflow.md` foram lidos e de como a execução respeitou esses arquivos.
4. Validação explícita do DoD.
5. Resultado da suíte.
6. Commit realizado.
7. Link ou nome do PR aberto.
