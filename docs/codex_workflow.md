# Codex Workflow: finance_control

## Papel deste arquivo

`docs/codex_workflow.md` define como o Codex deve executar trabalho técnico neste projeto. Este arquivo não substitui o contexto do projeto; ele organiza leitura obrigatória, respeito a escopo, testes, atualização de documentação, validação final e regras para commit/PR.

Leitura obrigatória antes de executar:
1. `docs/project_context.md`
2. `docs/codex_workflow.md`
3. quaisquer outros arquivos que o prompt mandar ler antes de começar.

## Regras Obrigatórias do Codex

1. Sempre considerar `docs/project_context.md` como base prioritária de contexto do projeto.
2. Sempre considerar `docs/codex_workflow.md` como base prioritária do processo de execução.
3. Sempre ler também os arquivos adicionais indicados no prompt.
4. Não contradizer decisões já tomadas em `docs/project_context.md`.
5. Respeitar objetivo, fora de escopo e DoD do prompt.
6. Não abrir escopo por conta própria.
7. Transformar itens críticos do DoD em testes sempre que possível.
8. Revisar os arquivos alterados quanto a:
   - mojibake;
   - encoding incorreto;
   - BOM residual;
   - problemas de formatação.
9. Executar a suíte completa antes de considerar a entrega concluída.

## Regra Crítica de Atualização dos Arquivos

O Codex deve manter estes arquivos atualizados sempre que necessário.

### Atualizar `docs/project_context.md` quando mudar

- estado do sistema;
- decisões do projeto;
- operação atual;
- próximos passos recomendados;
- limitações relevantes.

### Atualizar `docs/pm_workflow.md` quando mudar

- o processo esperado da LLM/PM;
- a forma de estruturar prompts;
- a forma de definir DoD;
- a forma de revisar PRs;
- a forma de conduzir o trabalho.

### Atualizar `docs/codex_workflow.md` quando mudar

- o processo esperado do executor técnico;
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
4. Implementar somente o necessário para o objetivo do PR.
5. Atualizar testes quando o DoD ou o risco exigir.
6. Atualizar documentação/contexto/processo quando necessário.
7. Fazer higiene final dos arquivos alterados.
8. Rodar a suíte completa.
9. Só então considerar commit e PR.

## Regras para Commit e PR

O Codex só pode commitar e abrir PR depois de:
- DoD cumprido;
- arquivos de contexto/processo atualizados quando necessário;
- suíte completa verde;
- higiene final concluída.

Se qualquer um desses pontos falhar, o trabalho ainda não está finalizado.

## Como Usar nos Próximos Prompts

- O PM deve mandar o Codex ler os arquivos relevantes antes de cada nova execução.
- O Codex deve obedecer essa leitura antes de implementar qualquer mudança.
- `docs/project_context.md`, `docs/pm_workflow.md` e `docs/codex_workflow.md` passam a fazer parte do processo padrão do projeto.
