# Registro de iteração de prompts

## Avaliação final - integração real de IA

### Versão 1: explicação livre após o score

Ideia inicial: enviar as red flags ao modelo e pedir uma explicação. Problema: o contrato ficava implícito e o modelo poderia contradizer o score ou omitir limitações.

### Versão 2: JSON e persona

Foram adicionados persona de analista de segurança, campos de saída e tom não alarmista. Problema: apenas escrever “responda em JSON” não garante JSON parseável nem uso de dados auditáveis.

### Versão 3: tools, schema e proteção de entrada

Versão atual em `prompts/system_prompt.txt`: tool obrigatória para o score, schema de structured output, validação semântica da recomendação, tags XML para isolar a vaga, instrução contra prompt injection e examples contrastivos. O agente limita o fluxo a três ciclos e cai para regras locais em qualquer violação do protocolo.

## Prompts que funcionaram

- "A partir dessa pasta, desenvolva todo o projeto" funcionou como prompt inicial porque a pasta continha especificacoes suficientes para inferir o produto, o escopo e a regra de nao integrar LLM.
- Separar a leitura das especificacoes antes de codar ajudou a preservar o dominio: modelo `Vaga`, `Analise`, `RedFlag`, `Denuncia` e roadmap de IA.
- Implementar primeiro o motor de regras isolado facilitou a criacao de testes e evitou acoplar a logica de score diretamente na interface.

## Pontos que exigiram decisao manual

- Os arquivos `03-functional-flows.md`, `04-ui-screens.md`, `06-architecture.md`, `08-observability.md` e `09-non-functional.md` eram citados, mas nao existiam na pasta. A solucao foi inferir esses fluxos a partir dos specs disponiveis e do PDF da avaliacao.
- FastAPI, Flask, Uvicorn e Pytest nao estavam instalados no ambiente. Para manter o projeto executavel sem download de dependencias, a aplicacao foi feita com `http.server`, `sqlite3` e testes com `unittest`.
- O endpoint publico ainda depende de exposicao externa pelo aluno, por exemplo ngrok ou deploy em uma plataforma gratuita.

## O que seria diferente em uma proxima iteracao

- Adicionar React + Vite se o ambiente de entrega permitir instalar dependencias.
- Criar uma suite de testes end-to-end no navegador.
- Substituir o extrator mockado por pipeline real de OCR/LLM apenas na proxima fase do curso.
