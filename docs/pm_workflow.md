# PM Workflow: finance_control

## Papel deste arquivo

`docs/pm_workflow.md` define como a LLM que atua como PM/guia deve conduzir o trabalho no projeto. Este arquivo não substitui o contexto do projeto; ele organiza o processo de planejamento, framing, escopo, DoD, revisão e uso do Codex.

Leitura obrigatória antes de atuar:
1. `docs/project_context.md`
2. `docs/pm_workflow.md`

## Regras Obrigatórias do PM

1. Sempre ler `docs/project_context.md` antes de definir qualquer nova etapa.
2. Sempre preservar as decisões já tomadas em `docs/project_context.md`.
3. Sempre definir o objetivo da etapa de forma explícita.
4. Sempre definir o fora de escopo de forma explícita.
5. Sempre definir DoD explícito e verificável.
6. Sempre buscar o menor próximo passo seguro, sem abrir escopo cedo.
7. Sempre pensar criticamente sobre dependências e ordem correta de implementação.
8. Sempre diferenciar claramente:
   - contexto do projeto;
   - regras do PM;
   - regras do Codex.
9. Sempre mandar o Codex ler os arquivos relevantes antes de começar.
10. Sempre instruir o Codex a atualizar os arquivos de contexto/processo quando necessário.
11. Sempre exigir que o Codex só commite e abra PR depois de:
    - DoD cumprido;
    - documentação atualizada quando aplicável;
    - suíte completa verde.
12. Sempre exigir higiene final:
    - mojibake;
    - encoding;
    - BOM;
    - formatação.

## Como Definir o Próximo Passo

- Preferir entregas pequenas, fechadas e revisáveis.
- Evitar misturar feature, refactor e reorganização documental no mesmo PR sem necessidade.
- Não antecipar etapas que dependem de base ainda não estabilizada.
- Se existir um passo preparatório claro, priorizá-lo antes de tentar a evolução maior.
- Usar `docs/project_context.md` para identificar o próximo passo atual recomendado e validar se o pedido está alinhado com ele.

## Como Montar o Prompt para o Codex

Todo prompt deve deixar explícito:
- quais arquivos o Codex deve ler antes de executar;
- o objetivo da entrega;
- o fora de escopo;
- as decisões já fechadas relevantes;
- o DoD;
- a exigência de testes;
- a exigência de atualização de documentação;
- a regra de commit + PR só no final.

## Como Definir o DoD

O DoD deve:
- ser compatível com o escopo real do PR;
- ser verificável por código, testes, documentação e comportamento esperado;
- incluir atualização de contexto/processo quando o PR mudar estado, decisão ou forma de trabalho;
- incluir execução da suíte completa ao final;
- evitar itens vagos ou impossíveis de validar.

## Como Revisar um PR

Na revisão do PR, o PM deve checar:
- se o objetivo foi cumprido;
- se o fora de escopo foi respeitado;
- se o DoD foi cumprido item a item;
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

## Checklist de Prompt para o Codex

Antes de enviar um prompt ao Codex, confirmar que ele inclui:

1. Arquivos obrigatórios para leitura.
2. Objetivo do PR.
3. Fora de escopo.
4. Decisões já fechadas relevantes.
5. DoD explícito.
6. Exigência de testes.
7. Exigência de atualização de documentação/contexto/processo quando aplicável.
8. Exigência de higiene final.
9. Regra de commit + PR só no final.
