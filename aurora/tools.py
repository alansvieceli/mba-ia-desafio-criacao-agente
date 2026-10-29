"""Tools do assistente. O apartamento vem sempre do state da sessão.

Nenhuma tool recebe apartamento como parâmetro: o modelo não tem como escolher
de quem são as reservas e os visitantes que ela lê ou grava.
"""

from datetime import date

from google.adk.tools import ToolContext

from . import db, regulamento


def _apartamento(tool_context):
    return tool_context.state["apartamento"]


def _area(texto):
    """Aceita o id ou o nome da área e devolve a área, ou None."""
    chave = texto.strip().lower()
    for a in db.areas().values():
        if chave in (a["id"], a["nome"].lower()):
            return a


def _data(texto):
    try:
        return date.fromisoformat(texto.strip()).isoformat()
    except ValueError:
        return None


def _pede_confirmacao(tool_context, acao, detalhes):
    """Deixa a ação pendente até a rota de confirmações responder."""
    tool_context.request_confirmation(hint=acao, payload={"acao": acao, "detalhes": detalhes})
    tool_context.actions.skip_summarization = True
    return {"status": "aguardando_confirmacao", "acao": acao}


def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador."""
    return {"reservas": db.reservas_do(_apartamento(tool_context))}


def consultar_disponibilidade(area: str, data: str, tool_context: ToolContext) -> dict:
    """Diz se uma área comum está livre ou ocupada numa data (AAAA-MM-DD).

    Args:
        area: id ou nome da área (salao-de-festas, churrasqueira, quadra).
        data: data no formato AAAA-MM-DD.
    """
    a, d = _area(area), _data(data)
    if not a or not d:
        return {"erro": "Área ou data inválida. Use uma área existente e a data como AAAA-MM-DD."}
    return {"area": a["id"], "data": d, "disponivel": db.area_livre(a["id"], d)}


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador numa data.

    Áreas com taxa geram cobrança e ficam pendentes até o morador confirmar.

    Args:
        area: id ou nome da área (salao-de-festas, churrasqueira, quadra).
        data: data no formato AAAA-MM-DD.
    """
    a, d = _area(area), _data(data)
    if not a or not d:
        return {"erro": "Área ou data inválida. Use uma área existente e a data como AAAA-MM-DD."}
    cobra = a["taxa"] > 0
    confirmacao = tool_context.tool_confirmation
    if cobra and not confirmacao:
        if not db.area_livre(a["id"], d):
            return {"status": "indisponivel", "mensagem": "Essa data já está ocupada."}
        return _pede_confirmacao(
            tool_context,
            f"Reservar {a['nome']} em {d} (taxa de R$ {a['taxa']:.2f})",
            {"area": a["id"], "data": d, "taxa": a["taxa"]},
        )
    if cobra and not confirmacao.confirmed:
        return {"status": "negada", "mensagem": "O morador não confirmou. Nada foi reservado."}
    codigo = db.reservar(_apartamento(tool_context), a["id"], d)
    if not codigo:
        return {"status": "indisponivel", "mensagem": "Essa data já está ocupada."}
    return {"status": "reservada", "codigo": codigo, "area": a["id"], "data": d, "taxa": a["taxa"]}


def cancelar_reserva(
    tool_context: ToolContext, codigo: str = "", area: str = "", data: str = ""
) -> dict:
    """Cancela uma reserva do apartamento do morador, sem confirmação.

    Informe o código da reserva ou então a área e a data.

    Args:
        codigo: código da reserva (opcional).
        area: id ou nome da área (opcional se houver código).
        data: data no formato AAAA-MM-DD (opcional se houver código).
    """
    a = _area(area) if area else None
    cancelada = db.cancelar(
        _apartamento(tool_context), codigo.strip(), a["id"] if a else "", _data(data) or ""
    )
    if not cancelada:
        # mesma resposta para "não existe" e "é de outro apartamento"
        return {"status": "nao_encontrada", "mensagem": "Você não tem uma reserva com esses dados."}
    return {"status": "cancelada", "codigo": cancelada}


def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados pelo apartamento do morador."""
    return {"visitantes": db.visitantes_do(_apartamento(tool_context))}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante numa data. Fica pendente até o morador confirmar.

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.
    """
    nome, d = nome.strip(), _data(data)
    if not nome or not d:
        return {"erro": "Informe o nome do visitante e a data como AAAA-MM-DD."}
    confirmacao = tool_context.tool_confirmation
    if not confirmacao:
        return _pede_confirmacao(
            tool_context, f"Autorizar a entrada de {nome} em {d}", {"nome": nome, "data": d}
        )
    if not confirmacao.confirmed:
        return {"status": "negada", "mensagem": "O morador não confirmou. Nada foi autorizado."}
    db.autorizar_visitante(_apartamento(tool_context), nome, d)
    return {"status": "autorizado", "nome": nome, "data": d}


def consultar_regulamento(assunto: str) -> dict:
    """Busca no regulamento do condomínio os artigos sobre um assunto.

    Args:
        assunto: poucas palavras-chave do assunto, como "piscina horário domingo".
    """
    trechos = regulamento.consultar(assunto)
    if not trechos:
        return {"trechos": "", "mensagem": "Nada encontrado no regulamento sobre isso."}
    return {"trechos": trechos}
