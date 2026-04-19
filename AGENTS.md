# AGENTS.md

Antes de alterar o repositório, leia:
- `README.md`
- `docs/project_context.md`
- `docs/coder_workflow.md`
- `docs/pm_workflow.md` somente quando a mudança tocar contexto, processo ou documentação de workflow

Regras recorrentes:
- trate `docs/project_context.md` como contexto técnico estável
- trate `docs/coder_workflow.md` como regra de execução técnica
- mantenha mudanças pequenas, focadas e revisáveis
- não mude comportamento funcional sem pedido explícito
- se a entrega alterar estado, decisão ou processo, atualize o arquivo correspondente no mesmo PR
- valide com `make test-docs` quando o PR for só de `docs/`; caso contrário, rode a suíte completa
