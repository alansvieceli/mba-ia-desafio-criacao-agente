# Residencial Aurora: assistente virtual

Assistente do aplicativo dos moradores do Residencial Aurora, construído com Google ADK e exposto por uma API em FastAPI. O modelo conduz a conversa; as regras críticas moram no código e valem não importa o que o morador escreva.

## Arquitetura

```
aurora/
  agentes.py      agente principal e especialistas
  tools.py        tools: único caminho para ler e gravar reservas e visitantes
  db.py           armazenamento SQLite (reservas e visitantes)
  regulamento.py  consulta ao regulamento por trechos
  api.py          rotas, Runner e serviço de sessões
  restaurar.py    comando que restaura os dados iniciais
```

Fluxo: o morador fala com o agente principal; ele transfere (`transfer_to_agent`) para um especialista; o especialista chama as tools. Os especialistas não transferem de volta (`disallow_transfer_to_parent` e `disallow_transfer_to_peers`), então a mensagem seguinte sempre recomeça no principal, que roteia de novo. Isso deixa a escolha do agente previsível, inclusive ao retomar uma confirmação.

| Agente | Responsabilidade | Como é acionado | Por quê |
| --- | --- | --- | --- |
| `aurora` (principal) | Entender o pedido e encaminhar. Não tem tools de dados e não recebe o regulamento. | É a raiz do `App`. | Um ponto único de entrada, sem poder para alterar nada. |
| `reservas` | Reservar, cancelar, listar e ver datas livres. | Transferência do principal. | Concentra as regras de área, taxa e data. |
| `visitantes` | Autorizar e listar visitantes. | Transferência do principal. | Autorizar libera acesso ao prédio, então fica isolado, com instruções e confirmação próprias. |
| `regulamento` | Responder dúvidas com base em `consultar_regulamento`. | Transferência do principal. | O texto do regulamento só aparece quando alguém pergunta sobre ele. |

Escolhi transferência (`sub_agents`) em vez de `AgentTool` porque a confirmação precisa voltar ao agente que a pediu, na mesma execução. Com `AgentTool` ela ficaria dentro de um Runner aninhado.

Armazenamento: SQLite em `estado/` (ignorado pelo Git). `condominio.db` guarda reservas e visitantes; `sessoes.db` guarda as sessões do ADK (`SqliteSessionService`). Os dois usam WAL. Se `condominio.db` não existe, ele é criado a partir de `dados/`.

Modelo: `gemini-2.5-flash` para todos os agentes, ou o que estiver em `AURORA_MODELO`.

## Garantias

**1. Cobrança ou acesso só com confirmação.**
`reservar_area` e `autorizar_visitante` ([aurora/tools.py](aurora/tools.py)) chamam `tool_context.request_confirmation(...)` em `_pede_confirmacao` e só gravam quando `tool_context.tool_confirmation.confirmed` é verdadeiro. Quem preenche `tool_confirmation` é o framework, a partir de um `FunctionResponse` que só a rota `POST /sessoes/{id}/confirmacoes` ([aurora/api.py](aurora/api.py), `responder_confirmacao`) cria. O texto do morador nunca chega lá, então "já confirmei aqui" não muda nada. A lista `confirmacoes_pendentes` é calculada em `_pendentes`: chamadas `adk_request_confirmation` dos eventos da sessão sem resposta. Se o `id` não está nessa lista (inexistente ou já respondido), a rota devolve `409` antes de executar qualquer coisa. A resposta é entregue ao agente certo repassando o `invocation_id` da pendência ao `runner.run_async`. A quadra, sem taxa, não pede confirmação; cancelar também não.

**2. Cada sessão pertence a um apartamento.**
`POST /sessoes` grava o apartamento em `state` ([aurora/api.py](aurora/api.py), `criar_sessao`). Toda tool lê `tool_context.state["apartamento"]` (`_apartamento` em [aurora/tools.py](aurora/tools.py)); nenhuma tool tem parâmetro de apartamento, e o modelo não tem como escolher outro. Consultar disponibilidade devolve só `disponivel: true/false`. Cancelar uma reserva que não é do apartamento devolve a mesma resposta de "não existe", sem confirmar nem negar que ela existe. Os especialistas também são instruídos a recusar pedidos sobre outros apartamentos (`REGRAS` em [aurora/agentes.py](aurora/agentes.py)), mas a garantia é a ausência do dado nas respostas das tools.

**3. Nada se perde no reinício.**
O `Runner` usa `SqliteSessionService` em arquivo ([aurora/api.py](aurora/api.py), `ciclo_de_vida`), e reservas e visitantes ficam no SQLite ([aurora/db.py](aurora/db.py)). Os códigos nunca se repetem: cancelar apenas marca `ativa = 0`, e `reservar` só sorteia um código que não existe na tabela, cancelado ou não.

**4. O regulamento é consultado, não carregado.**
Só a tool `consultar_regulamento` do especialista `regulamento` lê `dados/regulamento.md` ([aurora/regulamento.py](aurora/regulamento.py), `consultar`). Ela ranqueia os artigos pela pergunta e devolve os melhores de um único capítulo, o do artigo mais relevante, então um evento nunca contém texto de capítulo de outro assunto. O agente principal e os demais especialistas não têm o regulamento nas instruções.

**5. Dois moradores, uma reserva.**
A exclusividade vale na gravação: o índice único parcial `uq_reserva_ativa ON reservas (area, data) WHERE ativa = 1` ([aurora/db.py](aurora/db.py)) faz o próprio banco recusar a segunda reserva ativa. `reservar` captura o `IntegrityError` e devolve `None`, e a tool responde `indisponivel` como resposta normal. A conferência de agenda antes de pedir a confirmação serve só para não pedir cobrança de uma data já ocupada.

## Como rodar

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e uma chave do Google AI Studio. O uv instala o Python 3.12 se preciso. Não há serviço externo.

```bash
cp .env.example .env        # preencha GOOGLE_API_KEY
uv sync
uv run python -m aurora.restaurar     # restaura reservas e visitantes (e apaga as sessões)
uv run uvicorn aurora.api:api --port 8000
```

Variáveis do `.env`:

- `GOOGLE_API_KEY`: chave do Google AI Studio (obrigatória).
- `AURORA_MODELO`: modelo Gemini dos agentes (opcional; padrão `gemini-2.5-flash`).

O comando de restauração deve rodar com a API parada. Ele recria `estado/condominio.db` a partir de `dados/` e também apaga `estado/sessoes.db`. Para reiniciar a API sem perder nada, pare com Ctrl+C e rode de novo o comando de subida, sem restaurar.

API em `http://localhost:8000`:

- `POST /sessoes` com `{"apartamento": "101"}`
- `POST /sessoes/{session_id}/mensagens` com `{"texto": "..."}`
- `POST /sessoes/{session_id}/confirmacoes` com `{"id": "...", "confirmado": true}`
- `GET /sessoes/{session_id}/eventos`
- `GET /apartamentos/{numero}/reservas` e `GET /apartamentos/{numero}/visitantes`
