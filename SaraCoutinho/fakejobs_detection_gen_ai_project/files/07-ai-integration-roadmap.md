# 07 — Roadmap de Integração de IA (fora do escopo desta entrega)

> Este documento existe para demonstrar visão de arquitetura futura, sem que nenhum
> item aqui seja implementado com modelo real nesta entrega. Serve também como
> mapa entre o conteúdo do curso e onde ele se aplicaria neste projeto.

## Fase 1 — Embeddings e busca semântica
- Gerar **word embeddings** do texto da vaga e comparar via similaridade de cosseno
  com uma base vetorial de vagas já confirmadas como golpe ou legítimas.
- Ideia inspirada em modelos de embedding tipo CLIP (que aprendem representações
  compartilhadas entre modalidades) — aqui aplicado apenas a texto, mas o texto da
  vaga poderia futuramente ser combinado com print/imagem do anúncio (multimodal).
- Armazenar os vetores em uma extensão vetorial simples (ex: `sqlite-vss`) ou em
  arquivo, mantendo a filosofia "zero infraestrutura" do protótipo.

## Fase 2 — Classificador baseado em Transformer
- Treinar (ou fazer fine-tuning) um classificador supervisionado real usando o
  dataset **EMSCAD / "Real or Fake Job Posting Prediction"** (o mesmo que hoje só
  inspira os pesos do motor de regras mockado em `05-scoring-engine.md`) — desta vez
  treinando de fato sobre os textos (`description`, `company_profile`,
  `requirements`, `benefits`) e não só usando os metadados estruturais.
- Uso de **arquitetura Transformer** (mecanismo de **attention**) para classificar o
  texto da vaga diretamente, complementando (não substituindo) o motor de regras
  determinístico da Fase 0. O motor de regras atual pode servir de *baseline* para
  comparar o ganho de performance do modelo treinado.
- Tratar o forte desbalanceamento do dataset (~95% real / ~5% fraude) com técnicas
  como balanceamento de classes ou ponderação de perda — documentado como decisão de
  modelagem a ser tomada nesta fase futura, não implementada agora.
- **Tokenizer**: pipeline de tokenização do texto de entrada antes de qualquer
  inferência — hoje o "pré-processamento" já existe como mock em `extrator_mock.py`,
  e essa função seria substituída por um tokenizer real (ex: BPE/WordPiece).
- **Residual connections / rotary embeddings**: mencionados aqui como parte da
  arquitetura interna do modelo escolhido (ex.: um modelo Llama-like local via
  Ollama usa RoPE para embeddings posicionais) — não são algo que o projeto
  implementa, mas informam a escolha do modelo a ser rodado.

## Fase 3 — Modelo local via Ollama (privacidade)
- Dado que o texto da vaga pode conter dados pessoais indiretos (nomes, e-mails),
  a proposta é rodar o modelo de linguagem **localmente via Ollama**, evitando
  enviar dados sensíveis a uma API de terceiros.
- Trade-off documentado: modelos locais menores tendem a ter menor qualidade de
  explicação em linguagem natural do que uma API de LLM maior — decisão de
  privacidade vs. qualidade a ser revisitada.

## Fase 4 — Orquestração com LangGraph
- O fluxo hoje mockado como "extrair → validar regras → gerar relatório" viraria um
  grafo de estados no **LangGraph**, com nós como:
  1. `extrair_campos` (nó determinístico ou com LLM)
  2. `verificar_empresa` (nó com tool call a uma API de CNPJ real)
  3. `avaliar_padroes_linguisticos` (nó com modelo Transformer)
  4. `gerar_explicacao` (nó de geração em linguagem natural)
  5. `consolidar_veredito` (nó determinístico, combinando os sinais)
- Isso mantém o motor de regras atual como um dos nós do grafo, não descartando o
  trabalho desta entrega — apenas envolvendo-o em uma orquestração maior.

## Fase 5 — Geração de explicação com prompt engineering
- Onde hoje existe `descricao` fixa por red flag (`05-scoring-engine.md`), no futuro
  um LLM geraria a explicação em linguagem natural e personalizada, com prompt
  estruturado do tipo:
  ```
  Sistema: Você é um assistente que explica de forma clara e não alarmista por que
  uma vaga de emprego foi marcada como suspeita, com base nos sinais técnicos abaixo.
  Sinais: {lista_de_red_flags}
  Trecho da vaga: {texto_da_vaga}
  Gere uma explicação em até 3 frases, em português, para uma pessoa leiga.
  ```
- Técnicas de prompt engineering a considerar: exemplos positivos/negativos (few-shot)
  de tom adequado, e instrução explícita de não afirmar categoricamente "é golpe"
  (mitigar excesso de confiança do modelo).

## Riscos de "vibe coding" a monitorar quando a IA entrar de fato
- Uso de agente de codificação para gerar a integração de LLM sem revisão pode
  introduzir chamadas inseguras (prompt injection via texto da vaga colado pelo
  usuário, já que esse texto vem de fonte não confiável).
- Necessidade de sanitizar/isolar o conteúdo da vaga antes de usá-lo como parte de
  um prompt, para não permitir que o texto da "vaga" manipule instruções do sistema.
- Vetor de custo/latência: chamadas a LLM por análise podem não escalar bem sem
  cache ou motor de regras como filtro prévio (o motor atual já cumpre esse papel).
