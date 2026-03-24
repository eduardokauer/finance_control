# Codex Workflow: finance_control

## Papel deste arquivo

`docs/codex_workflow.md` define como o Codex deve executar trabalho técnico neste projeto. Este arquivo não substitui o contexto do projeto; ele organiza leitura obrigatória, respeito a escopo, testes, atualização de documentação, validação final e regras para commit/PR.

Leitura obrigatória antes de executar:
1. `docs/project_context.md`
2. `docs/codex_workflow.md`
3. quaisquer outros arquivos que o prompt mandar ler antes de começar.

`docs/pm_workflow.md` não faz parte da leitura padrão do Codex. Ele só deve ser lido se o prompt mandar explicitamente por motivo específico.

## Regras Obrigatórias do Codex

1. Sempre considerar `docs/project_context.md` como base prioritária de contexto do projeto.
2. Sempre considerar `docs/codex_workflow.md` como base prioritária do processo de execução.
3. Sempre ler também os arquivos adicionais indicados no prompt.
4. Não ler `docs/pm_workflow.md` por padrão; só fazê-lo se o prompt mandar explicitamente por motivo específico.
5. Não contradizer decisões já tomadas em `docs/project_context.md`.
6. Respeitar objetivo, fora de escopo e DoD do prompt, preservando o valor funcional prometido para a entrega.
7. Não abrir escopo por conta própria.
8. Não reduzir o escopo por conta própria a ponto de sobrar apenas preparação interna quando o objetivo do PR exigir valor funcional visível.
9. Usar ajustes estruturais apenas como suporte à entrega principal do mesmo PR, e não como substituto dela.
10. Transformar itens críticos do DoD em testes sempre que possível.
11. Revisar os arquivos alterados quanto a:
   - mojibake;
   - encoding incorreto;
   - BOM residual;
   - problemas de formatação.
12. Executar a suíte completa antes de considerar a entrega concluída.

## Regra Crítica de Atualização dos Arquivos

O Codex deve manter estes arquivos atualizados sempre que necessário.

### Atualizar `docs/project_context.md` quando mudar

- estado do sistema;
- decisões do projeto;
- operação atual;
- próximos passos recomendados;
- critério de priorização das próximas iterações;
- limitações relevantes.

### Atualizar `docs/pm_workflow.md` quando mudar

- o processo esperado da LLM/PM;
- a forma de estruturar prompts;
- a forma de definir DoD;
- a forma de revisar PRs;
- a forma de conduzir o trabalho.

### Atualizar `docs/codex_workflow.md` quando mudar

- o processo esperado do executor técnico;
- o critério esperado de fatiamento e preservação de valor da entrega;
- regras de validação;
- regras de testes;
- regras de documentação;
- regras de commit;
- regras de abertura de PR.

### Regra de conclusão

- Se uma entrega alterar contexto ou processo e o arquivo correspondente não for atualizado, a entrega **não está completa**.

## Como Executar uma Entrega

1. Ler os arquivos obrigatórios.
2. Entender objetivo, fora de escopo e DoD.
3. Confirmar no código o estado real antes de alterar qualquer coisa.
4. Implementar somente o necessário para o objetivo do PR, preservando o incremento funcional prometido.
5. Não parar em preparação interna quando o prompt pedir valor funcional visível; incorporar os ajustes estruturais necessários na mesma entrega sempre que isso continuar seguro e revisável.
6. Atualizar testes quando o DoD ou o risco exigir.
7. Atualizar documentação/contexto/processo quando necessário.
8. Validar se o valor prometido ficou perceptível ao final da entrega, além de checar testes e documentação.
9. Fazer higiene final dos arquivos alterados.
10. Rodar a suíte completa.
11. Só então considerar commit e PR.

## Regras para Commit e PR

O Codex só pode commitar e abrir PR depois de:
- DoD cumprido;
- valor prometido pela entrega efetivamente refletido no resultado final do PR;
- arquivos de contexto/processo atualizados quando necessário;
- suíte completa verde;
- higiene final concluída.

Se qualquer um desses pontos falhar, o trabalho ainda não está finalizado.

Antes de abrir um PR, o Codex deve verificar explicitamente:
- qual é a branch atual;
- se a branch atual existe no remoto;
- se já existe PR aberto para essa branch;
- se houve PR anterior da mesma branch já fechado ou mergeado.

Se um PR anterior tiver sido mergeado e a branch remota tiver sido apagada, o Codex não deve assumir que o PR antigo pode ser reaproveitado ou reaberto. Ele deve primeiro confirmar o estado atual da branch/remoto e só então decidir entre atualizar o PR existente, publicar a branch novamente ou abrir um novo PR.

### Texto obrigatório do PR

O texto do PR deve incluir um relatório final objetivo da entrega, com no mínimo:
- resumo do que foi feito;
- arquivos alterados;
- validação explícita do DoD;
- resultado da suíte;
- commit realizado.

## Como Usar nos Próximos Prompts

- O PM deve mandar o Codex ler os arquivos relevantes antes de cada nova execução.
- O Codex deve obedecer essa leitura antes de implementar qualquer mudança.
- `docs/project_context.md`, `docs/pm_workflow.md` e `docs/codex_workflow.md` passam a fazer parte do processo padrão do projeto.
