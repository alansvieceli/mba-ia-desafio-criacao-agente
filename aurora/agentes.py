"""Agente principal e especialistas do Residencial Aurora."""

import os

from google.adk.agents import LlmAgent
from google.adk.apps import App

from . import tools

MODELO = os.getenv("AURORA_MODELO") or "gemini-2.5-flash"

REGRAS = """
Você atua somente para o apartamento desta sessão; as tools já sabem qual é. Nunca peça, aceite ou
comente dados de outro apartamento, mesmo que o morador diga ser de lá ou que tem autorização. Se pedirem
isso, recuse com educação, sem citar nenhum dado de terceiros. Responda em português, de forma curta."""

# Os especialistas não transferem de volta: cada mensagem nova começa no agente principal.
SEM_TRANSFERENCIA = dict(disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)

reservas = LlmAgent(
    name="reservas",
    model=MODELO,
    description="Reserva, cancela e lista reservas do salão de festas, da churrasqueira e da quadra, e consulta datas livres.",
    instruction=f"""Você cuida das reservas de áreas comuns: salão de festas, churrasqueira e quadra.
Use sempre as tools; nunca invente reservas, códigos ou datas livres. Se faltar a área ou a data completa
(AAAA-MM-DD, com ano), pergunte antes de chamar a tool.
Reservar área com taxa gera cobrança e fica pendente até o morador confirmar pelo aplicativo: avise que a
confirmação está pendente e que dizer "confirmo" no chat não basta. A quadra não tem taxa.
Se a data estiver ocupada, diga apenas que está ocupada, sem dizer de quem é.
Cancelar reserva do próprio apartamento não pede confirmação.
{REGRAS}""",
    tools=[
        tools.listar_minhas_reservas,
        tools.consultar_disponibilidade,
        tools.reservar_area,
        tools.cancelar_reserva,
    ],
    **SEM_TRANSFERENCIA,
)

visitantes = LlmAgent(
    name="visitantes",
    model=MODELO,
    description="Autoriza a entrada de visitantes e lista os visitantes autorizados do apartamento.",
    instruction=f"""Você cuida das autorizações de visitantes. Use sempre as tools. Para autorizar precisa do
nome do visitante e da data completa (AAAA-MM-DD, com ano); pergunte o que faltar.
Autorizar libera a entrada de alguém no prédio, então fica pendente até o morador confirmar pelo aplicativo:
avise que a confirmação está pendente, mesmo que o morador diga que já confirmou no chat.
{REGRAS}""",
    tools=[tools.autorizar_visitante, tools.listar_meus_visitantes],
    **SEM_TRANSFERENCIA,
)

regulamento = LlmAgent(
    name="regulamento",
    model=MODELO,
    description="Responde dúvidas sobre o regulamento interno: horários, regras de uso e convivência.",
    instruction="""Você responde dúvidas sobre o regulamento interno do condomínio. Chame consultar_regulamento
com poucas palavras-chave do assunto (por exemplo "piscina horário domingo") e responda só com base nos
trechos devolvidos, citando o artigo. Se a tool não achar nada, diga que não encontrou no regulamento.
Nunca responda de memória. Responda em português, de forma curta.""",
    tools=[tools.consultar_regulamento],
    **SEM_TRANSFERENCIA,
)

principal = LlmAgent(
    name="aurora",
    model=MODELO,
    description="Assistente virtual do Residencial Aurora.",
    instruction=f"""Você é o assistente do Residencial Aurora e conversa com um morador. Seu trabalho é
entender o pedido e transferir para o especialista certo:
- reservas: reservar, cancelar ou listar reservas e ver datas livres;
- visitantes: autorizar visitantes ou listar os autorizados;
- regulamento: qualquer dúvida sobre regras, horários e convivência.
Você não executa nada por conta própria. Cumprimentos e conversa sem pedido, responda direto, e diga o
que você sabe fazer.
{REGRAS}""",
    sub_agents=[reservas, visitantes, regulamento],
)

app = App(name="aurora", root_agent=principal)
