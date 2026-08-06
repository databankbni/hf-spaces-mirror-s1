# 05 — Motor de Regras (Mock do futuro motor de IA)

> Esta é a peça central do "onde a IA atuaria". Nesta entrega é 100% determinística
> (regras + heurísticas), documentada aqui para ficar clara a diferença entre o que
> é mock hoje e o que vira modelo real no roadmap (`07-ai-integration-roadmap.md`).
>
> Diferente da versão anterior deste spec, os pesos abaixo não são arbitrários: são
> inspirados em achados de EDA (análise exploratória) publicados sobre o dataset
> **EMSCAD / "Real or Fake Job Posting Prediction"** (Kaggle, shivamb — 17.880 vagas,
> ~5% fraudulentas). Isso dá lastro real às regras, mesmo sem treinar um modelo.

## O que a EDA do dataset mostrou (resumo, base para as regras)
- Ausência de `has_company_logo` e ausência de `company_profile` foram os dois
  fatores com maior correlação com fraude (uma análise publicada aponta ausência de
  logo e de perfil da empresa como os mais correlacionados).
- Vagas fraudulentas tendem a ter descrição, requisitos e perfil de empresa mais
  curtos (menor contagem de caracteres) do que vagas reais.
- Ausência de perguntas de triagem (`has_questions`) também aparece associada a
  fraude com menor frequência que o logo, mas ainda relevante.
- Quando presente, a faixa salarial de vagas fraudulentas tende a ser irreal — muito
  alta para o cargo ou com uma faixa numérica estranha.
- Uma fração desproporcional de vagas fraudulentas exige pouca qualificação
  educacional (ex.: "Some High School Coursework"), possivelmente mirando candidatos
  mais vulneráveis.
- Palavras como "Data Entry", "Administrative", "Home Based", "Earn Daily" aparecem
  com mais frequência em títulos de vagas fraudulentas; vagas reais concentram
  termos como "Manager", "Developer", "Engineer".
- A maioria das vagas fraudulentas no dataset é do tipo `Full-time` e nível
  `Entry level`.

> Importante para o README: os números exatos de correlação variam entre as análises
> publicadas (diferentes autores, diferentes cortes de dados) — o motor abaixo usa
> essas tendências como **direção qualitativa dos pesos**, não como coeficientes
> estatisticamente calibrados. Isso é uma simplificação consciente, documentada aqui
> como tal.

## Catálogo de Red Flags

| Código | Descrição (exibida ao usuário) | Peso | Heurística mock (campo do dataset) |
|---|---|---|---|
| `SEM_LOGO_EMPRESA` | Anúncio não exibe logo da empresa | 20 | `has_company_logo == false` |
| `SEM_PERFIL_EMPRESA` | Anúncio não traz descrição da empresa | 20 | `company_profile` vazio ou ausente |
| `DESCRICAO_CURTA` | Descrição da vaga muito curta para o cargo anunciado | 10 | contagem de caracteres de `description` abaixo de um limiar |
| `SEM_PERGUNTAS_TRIAGEM` | Processo não inclui nenhuma pergunta de triagem | 10 | `has_questions == false` |
| `SALARIO_INCOMPATIVEL` | Faixa salarial irreal (muito alta ou formato estranho) para o cargo/senioridade | 20 | `salary_range` presente, mas fora da faixa de referência esperada para `required_experience`/`function` |
| `EDUCACAO_MINIMA_SALARIO_ALTO` | Exige pouca qualificação educacional mas promete salário alto | 15 | `required_education` em `{"Some High School", "High School", "Unspecified"}` combinado com `SALARIO_INCOMPATIVEL` |
| `TITULO_SUSPEITO` | Título da vaga usa termos associados a golpes ("Data Entry", "Home Based", "Earn Daily", "Ganhe Rápido", "Renda Extra") | 15 | correspondência de palavras-chave em `title` |
| `COBRANCA_ANTECIPADA` | Pedido de pagamento antes da contratação (taxa, curso, uniforme, exame) | 30 | keywords em `description`/`requirements`: "taxa", "pix", "boleto", "depósito", "curso obrigatório" — **sinal textual, não vem do dataset original, mas é o sinal mais grave em golpes reais brasileiros** |
| `CANAL_GENERICO` | Contato via e-mail genérico (@gmail, @hotmail) em vez de domínio próprio | 15 | regex no `canal_contato` extraído |
| `URGENCIA_EXCESSIVA` | Linguagem de urgência para pressionar decisão rápida | 10 | keywords: "urgente", "vaga por tempo limitado", "responda agora" |

> As duas últimas regras (`COBRANCA_ANTECIPADA`, `URGENCIA_EXCESSIVA`, `CANAL_GENERICO`)
> não vêm de colunas do dataset — o EMSCAD não tem uma coluna de "pedido de
> pagamento" — mas são sinais amplamente documentados em golpes de vaga reais no
> Brasil e complementam bem os sinais estruturais do dataset, que sozinhos não
> cobrem esse padrão. Vale registrar essa lacuna no README como limitação consciente
> do dataset (ele captura sinais estruturais/meta-dados de uma plataforma de
> recrutamento formal, não mensagens de WhatsApp não solicitadas).

## Cálculo do score
```
score_bruto = soma dos pesos das regras disparadas
score_normalizado = min(100, score_bruto)

if score_normalizado >= 60:
    veredito = "provavel_golpe"
elif score_normalizado >= 30:
    veredito = "atencao"
else:
    veredito = "provavel_legitima"
```

## Confiança do veredito
A confiança reflete quantos campos o sistema conseguiu extrair/avaliar (mesma lógica
de antes, agora sobre as 18 colunas do schema alinhado ao dataset):
```
if campos_extraidos >= 12: confianca = "alta"
elif campos_extraidos >= 7: confianca = "media"
else: confianca = "baixa"
```

## Casos de teste sugeridos (usar amostras reais do CSV, não só sintéticas)
1. **Caso real fraudulento do dataset** (`fraudulent == 1`): sem logo, sem perfil de
   empresa, salário incompatível → deve gerar score alto e veredito `provavel_golpe`.
2. **Caso real legítimo do dataset** (`fraudulent == 0`): com logo, com perfil de
   empresa detalhado, descrição longa → score baixo.
3. **Golpe clássico brasileiro (fora do padrão do dataset)**: contato via WhatsApp
   não solicitado, pede PIX de "taxa de cadastro" → mesmo com poucos campos
   estruturais preenchidos, `COBRANCA_ANTECIPADA` sozinho já deve levar a `atencao`
   ou `provavel_golpe`, mostrando o valor de complementar os sinais do dataset com
   sinais textuais locais.
4. **Caso ambíguo**: descrição curta mas sem cobrança nem pedido de documentos →
   veredito "atenção", não "provável golpe" (evitar falso positivo forte).

## Nota de honestidade (para o README)
Deixar explícito que: (a) o motor não entende linguagem, apenas casa regras e
palavras-chave; (b) os pesos são inspirados em tendências relatadas na EDA pública do
dataset EMSCAD, não em coeficientes de um modelo treinado; (c) o dataset é de vagas em
inglês, majoritariamente dos EUA, publicadas em uma plataforma formal — logo, sinais
como "sem logo" fazem sentido nesse contexto, mas golpes via WhatsApp/redes sociais no
Brasil têm um padrão diferente, coberto apenas parcialmente pelas regras textuais
adicionadas manualmente. Essa é exatamente a lacuna que a Fase 2 do roadmap (treinar
um classificador real sobre o dataset, combinado com dados brasileiros) resolveria.
