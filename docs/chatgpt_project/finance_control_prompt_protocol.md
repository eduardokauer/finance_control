# Prompt Protocol

## Objetivo
Definir qual artefato o ChatGPT deve gerar em cada etapa do trabalho.

## Ferramentas
- ChatGPT Project = refinamento, análise e geração de prompts
- Notion = registro curto de decisões e da fatia atual
- Claude = escritor preferencial do Notion
- Repositório = contexto técnico estável e regras de execução
- Coder/Codex = executor técnico

## Tipos de saída permitidos
1. Perguntas de refinamento uma por vez até fechar o escopo refinado
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
- Quando precisar citar ou localizar fontes principais do projeto, usar `docs/reference/system_links.md` como fonte única de verdade dos links canônicos.
- Evitar duplicar links em prompts e arquivos de apoio, salvo necessidade explícita.
- Quando a decisão ficar fechada na própria resposta, gerar o prompt da próxima etapa na mesma interação.
- Não exigir um novo comando do usuário para avançar quando já houver clareza suficiente para produzir o próximo artefato correto.
- Se a decisão estiver fechada e a próxima ação já for clara, a etapa atual da resposta deve ser a etapa de destino, e não permanecer em REFINAR.
- Para REGISTRAR_NOTION, ALINHAR_REPO e EXECUTAR, o artefato gerado agora só está completo se já incluir o prompt correspondente.

## Etapas e saída esperada

### REFINAR
Saída:
- entendimento atual
- lacuna principal
- próxima pergunta única, quando ainda houver bloqueio real
- ou prompt da próxima etapa, se a ambiguidade tiver sido resolvida na própria resposta

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
- análise crítica de diff/PR
- se necessário, prompt curto de correção
