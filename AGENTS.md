# AGENTS.md

Antes de alterar o repositório, leia:
- `README.md`
- `docs/project_context.md`
- `docs/coder_workflow.md`

Regras recorrentes:
- trate `docs/project_context.md` como contexto técnico estável
- trate `docs/coder_workflow.md` como o workflow técnico detalhado
- mantenha mudanças pequenas e revisáveis
- atualize o arquivo correspondente quando estado, decisão ou processo mudar
- valide com `make test-docs` se o PR for só de `docs/`; caso contrário, rode a suíte completa

## Encerramento padrão
- Quando houver alterações no repositório, o padrão é:
  1. validar
  2. commitar
  3. fazer push
  4. abrir draft PR
- Só não abrir PR se:
  - eu pedir explicitamente para não abrir;
  - não houver mudanças;
  - o ambiente não permitir push/PR.
- Se não conseguir abrir PR, reportar o motivo exato.


