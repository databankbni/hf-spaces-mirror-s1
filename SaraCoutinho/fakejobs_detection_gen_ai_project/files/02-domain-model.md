# 02 — Modelo de Domínio

> O schema de `Vaga` foi alinhado ao dataset público **EMSCAD / "Real or Fake Job
> Posting Prediction"** (Kaggle, shivamb — 17.880 vagas rotuladas, ~5% fraudulentas,
> Universidade do Egeu). Isso permite (a) usar o CSV real para popular o banco com
> exemplos realistas de vagas verdadeiras e falsas, e (b) alinhar o motor de regras
> mockado com sinais que uma análise estatística real já validou como relevantes.
> Fonte: `fake_job_postings.csv`.

## Entidades principais

### `Vaga`
Representa a oferta de emprego submetida para análise. Campos espelham as colunas do
dataset original (à exceção de `job_id`, que vira `id` interno).
| Campo | Tipo | Observação |
|---|---|---|
| id | UUID | PK |
| texto_bruto | text | conteúdo original colado/extraído (quando vem de input livre do usuário) |
| fonte | enum | `whatsapp`, `email`, `linkedin`, `redes_sociais`, `site`, `outro` |
| title | string | título da vaga |
| location | string, nullable | localização geográfica informada |
| department | string, nullable | departamento/área — alta taxa de ausência no dataset original, tratado como sinal fraco isoladamente |
| salary_range | string, nullable | faixa salarial (ex: "50000-60000") — ~84% ausente no dataset geral |
| company_profile | text, nullable | descrição da empresa |
| description | text, nullable | descrição detalhada da vaga |
| requirements | text, nullable | requisitos listados |
| benefits | text, nullable | benefícios oferecidos |
| telecommuting | boolean | vaga remota? |
| has_company_logo | boolean | anúncio exibe logo da empresa? |
| has_questions | boolean | processo inclui perguntas de triagem? |
| employment_type | enum, nullable | `Full-time`, `Part-time`, `Contract`, `Temporary`, `Other` |
| required_experience | enum, nullable | `Internship`, `Entry level`, `Associate`, `Mid-Senior level`, `Director`, `Executive`, `Not Applicable` |
| required_education | enum, nullable | `Bachelor's`, `High School`, `Master's`, `Associate`, `Certification`, `Some College`, `Some High School`, `Vocational`, `Unspecified` |
| industry | string, nullable | setor da empresa |
| function | string, nullable | função/área de atuação |
| canal_contato | string, nullable | e-mail/telefone/link identificado no texto (extraído, não é coluna original do dataset) |
| criado_em | datetime | |
| usuario_id | UUID (FK) | |

### `Analise`
Resultado da avaliação de uma `Vaga`.
| Campo | Tipo | Observação |
|---|---|---|
| id | UUID | PK |
| vaga_id | UUID (FK) | |
| score_risco | int (0–100) | quanto maior, mais suspeito |
| veredito | enum | `provavel_golpe`, `atencao`, `provavel_legitima` |
| confianca | enum | `baixa`, `media`, `alta` (baseada em qtde de sinais coletados) |
| criado_em | datetime | |

### `RedFlag`
Sinal individual identificado numa análise (ver `05-scoring-engine.md` para o catálogo).
| Campo | Tipo | Observação |
|---|---|---|
| id | UUID | PK |
| analise_id | UUID (FK) | |
| codigo | string | ex: `COBRANCA_ANTECIPADA` |
| descricao | string | texto explicativo (fixo, mockado) |
| peso | int | contribuição para o score |
| trecho_evidencia | string, nullable | trecho do texto que disparou a regra |

### `Denuncia`
Reporte colaborativo de uma vaga suspeita, feito por um usuário.
| Campo | Tipo | Observação |
|---|---|---|
| id | UUID | PK |
| vaga_id | UUID (FK) | |
| usuario_id | UUID (FK) | |
| motivo | string | texto livre |
| status | enum | `pendente`, `confirmada`, `rejeitada` |
| criado_em | datetime | |

### `Usuario`
| Campo | Tipo | Observação |
|---|---|---|
| id | UUID | PK |
| nome | string | |
| email | string | |
| criado_em | datetime | |

## Relacionamentos
```
Usuario 1---N Vaga 1---1 Analise 1---N RedFlag
Usuario 1---N Denuncia N---1 Vaga
```

## Diagrama (texto)
```
[Usuario] --< [Vaga] --1:1-- [Analise] --< [RedFlag]
                 |
                 └--< [Denuncia] >-- [Usuario]
```

## Observações de implementação (SQLite)
- Usar `TEXT` para UUID (SQLite não tem tipo UUID nativo) gerado na aplicação.
- `criado_em` armazenado em ISO-8601 (`TEXT`), nunca em `INTEGER` epoch, para
  legibilidade ao inspecionar o `.db` manualmente durante o desenvolvimento.
- Índices recomendados: `Vaga.usuario_id`, `Analise.vaga_id`, `RedFlag.analise_id`.

## Seed de dados a partir do dataset Kaggle
Para popular o SQLite com exemplos realistas (em vez de dados 100% inventados),
um script `scripts/seed_from_kaggle.py` deve:
1. Ler `fake_job_postings.csv` (baixado manualmente do Kaggle — não versionar o CSV
   completo no repositório por tamanho, apenas uma amostra pequena em `/seed/`).
2. Selecionar uma amostra balanceada (ex: 30 vagas reais + 30 fraudulentas) para não
   expor o desbalanceamento real (~95%/5%) na demo.
3. Mapear as colunas do CSV diretamente para os campos de `Vaga` acima.
4. Gravar via o mesmo repositório (`vaga_repo.py`) usado pela aplicação, garantindo
   que os dados de exemplo passem pelo mesmo caminho de código dos dados reais.
