# Specs — VagaCheck

Este diretório contém a especificação completa do projeto **VagaCheck**, organizada
para servir de guia direto ao agente de codificação (Claude Code, Cursor, etc.) e,
posteriormente, de base para o README final da entrega.

**Base de dados de referência:** o schema de `Vaga` e os pesos do motor de regras
mockado são inspirados no dataset público **EMSCAD / "Real or Fake Job Posting
Prediction"** (Kaggle, shivamb). Baixe `fake_job_postings.csv` do Kaggle e use uma
amostra pequena para o script de seed (`02-domain-model.md`, seção "Seed de dados").

## Como usar com o agente de codificação
Não jogue todos os arquivos de uma vez em um prompt gigante. Siga a ordem abaixo,
peça uma parte por vez, teste, e só então avance — é exatamente a dica do enunciado
("construa incrementalmente").

1. `01-business.md` → alinhe o entendimento do problema com o agente antes de pedir
   qualquer código.
2. `02-domain-model.md` → peça a criação dos modelos SQLite/SQLAlchemy e migrations.
3. `06-architecture.md` → peça o esqueleto do backend (rotas vazias, estrutura de
   pastas) e do frontend (rotas React, layout base).
4. `05-scoring-engine.md` → peça a implementação do motor de regras isoladamente,
   com testes usando os casos de teste sugeridos no próprio arquivo.
5. `03-functional-flows.md` + `04-ui-screens.md` → peça uma tela por vez, testando
   a navegação entre elas antes de avançar.
6. `08-observability.md` → adicione logging/health-check/dashboard por último, quando
   o fluxo principal já estiver funcional.
7. `09-non-functional.md` → revisão final (CORS, validação, mensagens de erro).
8. `07-ai-integration-roadmap.md` → não vira código nesta fase — usar como seção do
   README final, explicando "como a IA será integrada no futuro".

## Índice
| Arquivo | Conteúdo |
|---|---|
| `01-business.md` | Problema, objetivo, público-alvo, métricas |
| `02-domain-model.md` | Entidades, relacionamentos, esquema de dados |
| `03-functional-flows.md` | Casos de uso e fluxos |
| `04-ui-screens.md` | Telas, wireframes textuais, componentes |
| `05-scoring-engine.md` | Catálogo de red flags e cálculo de score (mock) |
| `06-architecture.md` | Stack, camadas, contratos de API, decisões |
| `07-ai-integration-roadmap.md` | Onde entrariam LLM/embeddings/LangGraph no futuro |
| `08-observability.md` | Logging, métricas, health check |
| `09-non-functional.md` | Segurança, privacidade, performance, manutenibilidade |

## Dica para o README final da entrega
Ao escrever o README da entrega, aproveite estes specs para preencher diretamente:
- **Descrição do problema/solução** → resume de `01-business.md`
- **Escolhas de design** → resume de `06-architecture.md` (seção de decisões)
- **O que funcionou / o que não funcionou** → precisa ser escrito *durante* o
  desenvolvimento — anote aqui mesmo, em um `CHANGELOG-prompts.md`, os prompts que
  deram bons e maus resultados, para não perder o registro.
