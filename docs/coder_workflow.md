# Coder Workflow: finance_control

## Papel deste arquivo

Este arquivo define a execução técnica no repositório. Ele não cobre refinamento de produto.

## Leitura obrigatória

Antes de alterar qualquer coisa, ler:
1. `README.md`
2. `AGENTS.md`
3. `docs/project_context.md`
4. `docs/coder_workflow.md`
5. outros arquivos explicitamente citados no pedido

Se a mudança tocar processo ou compatibilidade de workflow, ler também `docs/pm_workflow.md`.

## Regras de execução

- Tratar `docs/project_context.md` como contexto técnico estável.
- Respeitar o objetivo, o fora de escopo e o DoD do pedido.
- Fazer o menor conjunto de mudanças que entregue o objetivo.
- Não reabrir decisões de produto nem centralizar refinamento aqui.
- Atualizar `docs/project_context.md` quando estado, decisão ou limitação técnica mudar.
- Atualizar `docs/coder_workflow.md` quando o processo de execução mudar.
- Manter encoding, formatação e texto limpos.

## Validação

- PR só com `docs/` alterado: `make test-docs` ou `python scripts/check_docs.py docs`
- Qualquer mudança fora de `docs/`: suíte completa do projeto
- Se a validação falhar, corrigir e repetir até ficar verde

## Commit e PR

- Commitar só depois de DoD, documentação e validação.
- Abrir PR só no final.
- A resposta final deve listar resumo, arquivos alterados, validação e commit.
- Use uma branch nova para trabalho novo, salvo continuação do mesmo PR.

## Higiene de thread
- Novo objetivo, nova fatia ou novo PR devem começar em thread nova.
- Use `/compact` apenas para continuar a mesma fatia quando a thread estiver longa.
- Não reutilize thread antiga para trabalho novo.
- Se a tarefa parecer um novo objetivo, sinalize isso explicitamente.