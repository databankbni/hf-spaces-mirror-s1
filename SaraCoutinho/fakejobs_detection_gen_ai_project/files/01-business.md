# 01 — Especificação de Negócio

## Nome do projeto
**VagaCheck** — plataforma de triagem de vagas de emprego suspeitas

## Problema
Golpes de vaga de emprego cresceram no Brasil nos últimos anos, explorando urgência,
esperança e a necessidade de renda de quem está desempregado. O golpista imita etapas
comuns de um processo seletivo real (contato profissional, entrevista rápida, promessa
de contratação) para roubar dados pessoais (CPF, RG, selfie, dados bancários) ou cobrar
taxas falsas (exame, uniforme, curso, "liberação da vaga").

O problema é difícil de resolver de forma trivial porque:
- os golpes evoluem e imitam cada vez melhor a linguagem corporativa legítima;
- o candidato costuma estar em posição vulnerável (urgência por renda), o que reduz o
  senso crítico no momento da decisão;
- os sinais de fraude são múltiplos e combinados (nenhum sinal isolado é conclusivo —
  é a combinação de fatores que forma o veredito).

## Objetivo do produto
Dado o texto (ou print/PDF) de uma oferta de vaga, o sistema deve:
1. Extrair os campos estruturados relevantes (empresa, canal de contato, salário,
   forma de contratação, exigências, etc.);
2. Avaliar a vaga contra um conjunto de regras/sinais de risco conhecidos;
3. Apresentar um veredito (score de risco + nível de confiança) com explicação de
   **por que** cada sinal foi levantado;
4. Manter um histórico de análises do usuário;
5. Permitir que a comunidade reporte vagas suspeitas, alimentando uma base coletiva;
6. (Futuro — fora do escopo desta entrega) usar um LLM para gerar explicações em
   linguagem natural e detectar padrões mais sutis via embeddings semânticos.

## Base de dados de referência
O projeto usa como referência estrutural e para popular exemplos o dataset público
**EMSCAD / "Real or Fake Job Posting Prediction"** (Kaggle, autor shivamb — 17.880
vagas rotuladas por pesquisadores da Universidade do Egeu, ~5% marcadas como
fraudulentas). Ele fornece:
- o **schema de campos** de uma vaga real (título, localização, descrição, perfil da
  empresa, se tem logo, se tem perguntas de triagem, faixa salarial, etc.) — usado
  para desenhar o modelo de domínio (`02-domain-model.md`);
- **achados de EDA já publicados** (correlações entre ausência de logo/perfil de
  empresa e fraude, texto mais curto em vagas falsas, salários irreais, etc.) que dão
  lastro real aos pesos do motor de regras mockado (`05-scoring-engine.md`), em vez
  de heurísticas totalmente inventadas;
- uma base para, no futuro (fora do escopo desta entrega), **treinar de fato** um
  classificador supervisionado — ver `07-ai-integration-roadmap.md`.

> Limitação importante: o dataset é majoritariamente de vagas em inglês publicadas em
> uma plataforma formal de recrutamento, o que cobre bem sinais estruturais (logo,
> perfil da empresa, texto curto) mas não cobre golpes tipicamente brasileiros via
> WhatsApp/redes sociais com pedido direto de pagamento — por isso o motor de regras
> combina sinais do dataset com regras textuais adicionais desenhadas manualmente.

## Escopo desta entrega (Avaliação Intermediária)
- **Sem integração de LLM/modelo de IA real.** Toda a "inteligência" é um motor de
  regras determinístico e transparente (ver `05-scoring-engine.md`), tratado como
  mock/placeholder do que futuramente seria um pipeline com IA generativa.
- Foco total em: estrutura de telas, navegação, formulários, persistência local
  (SQLite), e clareza do fluxo de decisão.

## Público-alvo
- Pessoas em busca de emprego, principalmente as que recebem contatos não solicitados
  por WhatsApp, e-mail ou redes sociais.
- Uso pessoal após o curso: o autor do projeto pretende usar/evoluir a ferramenta para
  checagem própria e de familiares.

## Métricas de sucesso (mockadas nesta fase, reais na fase com IA)
| Métrica | Definição | Fase atual |
|---|---|---|
| Taxa de detecção de red flags | % de sinais conhecidos identificados corretamente | Determinística (regras) |
| Falsos positivos | Vagas legítimas marcadas como suspeitas | Medida manualmente com casos de teste |
| Tempo até veredito | Tempo entre input e relatório | Deve ser instantâneo (sem chamada de rede a LLM) |
| Engajamento | Vagas analisadas por usuário, denúncias enviadas | Contadores simples no dashboard |

## Fora de escopo (nesta entrega)
- Login/autenticação robusta (pode ser mockado com usuário único ou sessão simples)
- Verificação real de CNPJ/empresa em bases externas (mockado)
- Qualquer chamada a API de LLM (proibido pelo enunciado da avaliação)
- Notificações push/e-mail reais (mockadas na UI)
