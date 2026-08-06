# Elevator pitch - 3 minutos

## 0:00-0:30 - O problema e a solução

“O VagaCheck ajuda candidatos a identificar sinais de golpe em ofertas de emprego. A pessoa cola a vaga e recebe um score auditável, as evidências encontradas e uma explicação em linguagem simples com o próximo passo mais seguro.”

## 0:30-2:30 - Decisões de LLM

“Escolhi o qwen2.5:1.5b local via Ollama porque vagas podem conter dados pessoais, ele suporta tools e a demonstração roda em hardware modesto sem API paga. O trade-off é menor aderência a tools do que modelos grandes; por isso existe validação e fallback.

Usei chamada HTTP direta, não LangChain, porque o fluxo tem duas tools e até três ciclos. Assim o tool calling e os erros ficam visíveis, com menos dependências.

O system prompt define persona, limites e formato JSON. A vaga entra entre tags como dado não confiável, então um texto do tipo ‘ignore as instruções’ não ganha prioridade. Dois few-shots ensinam o tom para alto e baixo risco.

A tool obrigatória calcula o score com regras auditáveis; o LLM não pode alterá-lo. Como o modelo de 1,5B omitiu tool calls nos testes, o modo padrão faz um preflight orquestrado e registra essa decisão; modelos maiores podem usar o modo autônomo. A segunda tool consulta apenas casos locais e declara que similaridade não confirma fraude. A resposta passa por schema e validação semântica.

Usei temperatura 0.2, top-p 0.9, seed 42 e limite de 320 tokens: baixa variação é mais adequada para segurança e JSON, mas 0.2 preserva naturalidade.”

## 2:30-3:00 - O que funcionou e o que não funcionou

“Funcionou separar decisão de explicação e validar a recomendação contra a tool. A versão anterior não tinha LLM real e apenas prometia IA futura; isso foi corrigido. Modelos locais podem falhar no protocolo, então a aplicação mostra explicitamente o fallback e nunca apresenta uma saída inválida como se fosse confiável.”

## Perguntas prováveis

**Por que temperatura 0.2 e não 0 ou 0.7?** 0 é um baseline estável, mas pode deixar a explicação mecânica. 0.7 aumenta diversidade sem vantagem para uma tarefa de segurança estruturada. 0.2 equilibra naturalidade e previsibilidade.

**O que acontece com input malicioso?** O system prompt manda tratar a vaga como dado, os caracteres de tags são escapados e o modelo não recebe tools perigosas. Além disso, score e recomendação são validados fora do modelo. Isso reduz o risco, mas não prova imunidade; há um caso adversarial no experimento.

**Por que não LangChain?** Duas tools e um loop curto não justificam dependência e abstração adicionais. LangGraph seria adequado com várias ramificações, human-in-the-loop e retries por nó.

**O LLM decide se é golpe?** Não. A tool determinística produz score e veredito. O LLM explica sinais e sugere ações coerentes com esse resultado.

**O que muda com modelo pago?** Provavelmente melhora aderência ao schema, tool calling e redação, mas aumenta custo e envia dados para terceiros. O cliente está isolado para permitir a troca.

**Por que não RAG ou multiagente?** Não há corpus validado nem tarefas independentes suficientes. Usá-los agora acrescentaria complexidade sem evidência de ganho.
