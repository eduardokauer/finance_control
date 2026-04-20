# finance_control — stable brief

## Produto
Aplicação pessoal de controle financeiro com ingestão de extrato bancário e fatura, categorização, conciliação assistida e análises financeiras.

## Escopo permanente do produto
- consolidar lançamentos financeiros pessoais
- manter histórico auditável
- apoiar categorização consistente
- permitir conciliação entre conta e fatura
- gerar análises financeiras úteis para tomada de decisão

## Stack principal
- FastAPI
- PostgreSQL
- SQLAlchemy
- Jinja2
- HTMX
- Pytest
- Docker Compose
- Make como orquestração externa
- Supabase como Postgres gerenciado

## Restrições fixas
- preservar separação entre decisão funcional e execução técnica

## Operating model
- ChatGPT refina e gera prompts
- Notion registra decisões curtas e a fatia atual
- Coder/Codex executa tecnicamente
- Claude escreve no Notion quando necessário
