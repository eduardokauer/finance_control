# Prompt protocol

## Objetivo
Definir qual artefato o ChatGPT deve gerar em cada etapa do trabalho.

## Ferramentas
- ChatGPT Project = refinamento, análise e geração de prompts
- Notion = registro curto de decisões e da fatia atual
- Claude = escritor preferencial do Notion
- Repositório = contexto técnico estável e regras de execução
- Coder/Codex = executor técnico

## Tipos de saída permitidos
1. Pergunta única de refinamento
2. Prompt para Claude atualizar o Notion
3. Prompt para Coder/Codex alinhar documentação do repositório
4. Prompt para Coder/Codex implementar uma fatia
5. Revisão crítica de diff/PR
6. Prompt curto de correção pós-review

## Regras
- Não gerar prompt de execução se a fatia ainda estiver ambígua.
- Não repetir contexto estável já coberto no repositório.
- Preferir prompts curtos e cirúrgicos.
- Sempre explicitar:
  - objetivo
  - escopo
  - fora de escopo
  - DoD
- Para Notion, gerar prompt para Claude.
- Para repositório ou código, gerar prompt para Coder/Codex.

## Etapas e saída esperada

### REFINAR
Saída:
- entendimento atual
- lacuna principal
- próxima pergunta única

### REGISTRAR_NOTION
Saída:
- prompt para Claude registrar decisão e/ou atualizar fatia atual

### ALINHAR_REPO
Saída:
- prompt para Coder/Codex ajustar arquivos de contexto técnico e workflow do repositório

### EXECUTAR
Saída:
- prompt para Coder/Codex implementar uma única fatia pronta

### REVISAR
Saída:
- análise crítica do diff/PR
- se necessário, prompt curto de correção