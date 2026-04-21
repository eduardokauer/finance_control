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
- Nunca trabalhar direto na branch `develop` ou main.
- Antes de criar uma nova branch, verificar qual branch está mais atual `develop`ou `main` e começar uma nova branch a partir dela.
- PRs devem sempre ser abertos da branch de trabalho para a `develop`
- Quando finalizar uma alteração, obrigatoriamente revisa testes ante de rodar a suite de testes. Se tiver ajustes claros ou novos testes necessários, fazer os ajustes e criar os testes antes de rodar a suite completa de testes.

## Validação

- Antes de rodar testes, sempre verificar se existe algum ajuste óbvio que precisa ser feito e fazer antes de rodar os testes.
- Antes de rodar os testes, verifique se todos os testes necessários foram desenolvidos e só depois de criálos, execute os testes.
- PR só com `docs/`, `AGENTS.md` ou `README.md` alterado: `make test-docs` ou `python scripts/check_docs.py docs`
- Qualquer mudança fora de `docs/`, `AGENTS.md` ou `README.md`: suíte completa do projeto
- Se a validação falhar, corrigir e repetir até ficar verde

## Commit e PR

- Commitar só depois de DoD, documentação e validação.
- Abrir PR só no final.
- A resposta final deve listar resumo, arquivos alterados, validação e commit.
- Use uma branch nova para trabalho novo, salvo continuação do mesmo PR.

## Higiene de thread
- Não reutilize thread antiga para trabalho novo.
- Se a tarefa parecer um novo objetivo, sinalize isso explicitamente.
- Novo objetivo, nova fatia ou novo PR devem começar em thread nova.
- Use `/compact` apenas para continuar a mesma fatia quando a thread estiver longa.

