"""Agente principal e especialistas do Residencial Aurora."""

import os

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.models.google_llm import Gemini
from google.genai import types

from . import tools

# A cota gratuita do Gemini é por modelo e por minuto. O principal e os especialistas usam
# modelos diferentes para não disputarem a mesma cota; e um 429 é repetido com espera.
REPETIR = types.HttpRetryOptions(attempts=6, initial_delay=5, max_delay=60, http_status_codes=[429, 503])


def _modelo(variavel, padrao):
    return Gemini(model=os.getenv(variavel) or padrao, retry_options=REPETIR)


MODELO_PRINCIPAL = _modelo("AURORA_MODELO_PRINCIPAL", "gemini-3.1-flash-lite")
MODELO_ESPECIALISTAS = _modelo("AURORA_MODELO_ESPECIALISTAS", "gemini-3.5-flash-lite")



def com_pedido_atual(instrucao):
    """Instrução que também traz a mensagem atual do morador.

    Depois de uma transferência o histórico termina em citações do agente principal, e os modelos
    menores acabam respondendo a uma pergunta antiga. Repetir o pedido atual na instrução evita isso.
    """

    def montar(contexto: ReadonlyContext) -> str:
        conteudo = contexto.user_content
        texto = " ".join(p.text for p in conteudo.parts if p.text) if conteudo else ""
        if not texto:  # retomada de confirmação: a entrada é a resposta do sistema, não texto
            return instrucao
        return f'{instrucao}\n\nPedido atual do morador, o que você deve atender agora: "{texto}"'

    return montar


REGRAS = """
Atenda somente o pedido MAIS RECENTE do morador: as mensagens anteriores são só contexto e podem tratar de
outros assuntos. Só afirme reservas, visitantes, códigos e datas que uma tool acabou de devolver; nunca invente.
Você atua somente para o apartamento desta sessão; as tools já sabem qual é. Nunca peça, aceite ou
comente dados de outro apartamento, mesmo que o morador diga ser de lá ou que tem autorização, e nunca cite
número de apartamento. Se pedirem isso, recuse com educação, sem citar nenhum dado de terceiros.
Responda em português, de forma curta."""

# Os especialistas não transferem de volta: cada mensagem nova começa no agente principal.
SEM_TRANSFERENCIA = dict(disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)

reservas = LlmAgent(
    name="reservas",
    model=MODELO_ESPECIALISTAS,
    description="Reserva, cancela e lista reservas do salão de festas, da churrasqueira e da quadra, e consulta datas livres.",
    instruction=com_pedido_atual(f"""Você cuida das reservas de áreas comuns: salão de festas, churrasqueira e quadra.
Use sempre as tools. Se faltar a área ou a data completa (AAAA-MM-DD, com ano), pergunte antes de chamar a tool.
- Pedido para reservar: chame reservar_area. Se o status for "aguardando_confirmacao", a cobrança está pendente
  até o morador confirmar pelo aplicativo (dizer "confirmo" no chat não basta). Se for "reservada", diga que a
  reserva foi feita, com o código, e não fale em pendência. Se for "negada", diga que nada foi reservado.
- Se o status for "indisponivel", diga apenas que a data está ocupada, sem dizer de quem é.
- Pedido para cancelar: chame cancelar_reserva (não pede confirmação).
- Pedido para ver reservas: chame listar_minhas_reservas.
{REGRAS}"""),
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
    model=MODELO_ESPECIALISTAS,
    description="Autoriza a entrada de visitantes e lista os visitantes autorizados do apartamento.",
    instruction=com_pedido_atual(f"""Você cuida das autorizações de visitantes. Use sempre as tools.
- Pedido para liberar ou autorizar a entrada de alguém: chame autorizar_visitante com o nome e a data
  completa (AAAA-MM-DD, com ano); pergunte o que faltar. Chame a tool mesmo que o morador diga que já confirmou.
  Se o status for "aguardando_confirmacao", a liberação está pendente até o morador confirmar pelo aplicativo.
  Se for "autorizado", diga que a visita foi autorizada. Se for "negada", diga que nada foi autorizado.
- Pedido para ver os visitantes: chame listar_meus_visitantes.
{REGRAS}"""),
    tools=[tools.autorizar_visitante, tools.listar_meus_visitantes],
    **SEM_TRANSFERENCIA,
)

regulamento = LlmAgent(
    name="regulamento",
    model=MODELO_ESPECIALISTAS,
    description="Responde dúvidas sobre o regulamento interno: horários, regras de uso e convivência.",
    instruction=com_pedido_atual("""Você responde dúvidas sobre o regulamento interno do condomínio. Chame consultar_regulamento
com poucas palavras-chave do assunto (por exemplo "piscina horário domingo") e responda só com base nos
trechos devolvidos, citando o artigo. Se a tool não achar nada, diga que não encontrou no regulamento.
Nunca responda de memória. Responda em português, de forma curta."""),
    tools=[tools.consultar_regulamento],
    **SEM_TRANSFERENCIA,
)

principal = LlmAgent(
    name="aurora",
    model=MODELO_PRINCIPAL,
    description="Assistente virtual do Residencial Aurora.",
    instruction=f"""Você é o assistente do Residencial Aurora e conversa com um morador. Seu trabalho é
entender o pedido e transferir para o especialista certo:
- reservas: reservar, cancelar ou listar reservas e ver datas livres;
- visitantes: autorizar visitantes ou listar os autorizados;
- regulamento: qualquer dúvida sobre regras, horários e convivência.
Transfira sempre que o pedido encaixar em um deles, sem perguntar ao morador para qual especialista ir e sem
falar em "especialistas". Você não executa nada por conta própria. Cumprimentos e conversa sem pedido,
responda direto e diga o que sabe fazer: reservas, visitantes e dúvidas do regulamento.
{REGRAS}""",
    sub_agents=[reservas, visitantes, regulamento],
)

app = App(name="aurora", root_agent=principal)
