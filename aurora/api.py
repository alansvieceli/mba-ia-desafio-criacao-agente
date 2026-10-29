"""API do assistente: sessões, mensagens, confirmações, eventos e rotas de verificação."""

import asyncio
import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google.adk.runners import Runner
from google.adk.sessions import SqliteSessionService
from google.genai import types
from pydantic import BaseModel

load_dotenv()

from . import agentes, db  # noqa: E402  (depois do load_dotenv: o modelo lê o .env)

NOME_CONFIRMACAO = "adk_request_confirmation"
USUARIO = "morador"  # o apartamento mora no state da sessão, não no user_id

servico_sessoes: SqliteSessionService
runner: Runner
travas = defaultdict(asyncio.Lock)  # uma execução por vez em cada sessão


@asynccontextmanager
async def ciclo_de_vida(_):
    global servico_sessoes, runner
    db.iniciar()
    # WAL: duas aprovações simultâneas em sessões diferentes não se bloqueiam
    with sqlite3.connect(db.BANCO_SESSOES) as conexao:
        conexao.execute("PRAGMA journal_mode=WAL")
    servico_sessoes = SqliteSessionService(str(db.BANCO_SESSOES))
    runner = Runner(app=agentes.app, session_service=servico_sessoes)
    yield


api = FastAPI(lifespan=ciclo_de_vida)


class NovaSessao(BaseModel):
    apartamento: str


class NovaMensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


async def _sessao(session_id):
    sessao = await servico_sessoes.get_session(
        app_name=agentes.app.name, user_id=USUARIO, session_id=session_id
    )
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    return sessao


def _pendentes(eventos):
    """Confirmações pedidas e ainda sem resposta do morador, lidas dos eventos."""
    respondidas = {
        r.id for e in eventos if e.author == "user" for r in e.get_function_responses()
    }
    pendentes = []
    for e in eventos:
        for chamada in e.get_function_calls():
            if chamada.name == NOME_CONFIRMACAO and chamada.id not in respondidas:
                payload = (chamada.args.get("toolConfirmation") or {}).get("payload") or {}
                pendentes.append(
                    {
                        "id": chamada.id,
                        "invocation_id": e.invocation_id,
                        "acao": payload.get("acao", ""),
                        "detalhes": payload.get("detalhes", {}),
                    }
                )
    return pendentes


async def _executar(session_id, conteudo, invocation_id=None):
    resposta = ""
    try:
        async for evento in runner.run_async(
            user_id=USUARIO, session_id=session_id, new_message=conteudo, invocation_id=invocation_id
        ):
            if evento.is_final_response() and evento.content and evento.content.parts:
                texto = "".join(p.text or "" for p in evento.content.parts if not p.thought)
                resposta = texto or resposta
    except Exception as erro:  # falha do modelo (cota, rede): resposta clara, não 500 mudo
        raise HTTPException(502, f"Falha ao falar com o modelo: {erro}") from erro
    sessao = await _sessao(session_id)
    pendentes = [
        {k: v for k, v in p.items() if k != "invocation_id"} for p in _pendentes(sessao.events)
    ]
    return {"resposta": resposta, "confirmacoes_pendentes": pendentes}


@api.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao):
    if corpo.apartamento not in db.apartamentos():
        raise HTTPException(422, "Apartamento desconhecido.")
    sessao = await servico_sessoes.create_session(
        app_name=agentes.app.name, user_id=USUARIO, state={"apartamento": corpo.apartamento}
    )
    return {"session_id": sessao.id}


@api.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: NovaMensagem):
    await _sessao(session_id)
    conteudo = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
    async with travas[session_id]:
        return await _executar(session_id, conteudo)


@api.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao):
    async with travas[session_id]:
        sessao = await _sessao(session_id)
        pedido = next((p for p in _pendentes(sessao.events) if p["id"] == corpo.id), None)
        if not pedido:
            raise HTTPException(409, "Não existe confirmação pendente com esse id nesta sessão.")
        # a resposta volta ao agente que pediu, pela mesma execução (invocation_id)
        conteudo = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=corpo.id, name=NOME_CONFIRMACAO, response={"confirmed": corpo.confirmado}
                    )
                )
            ],
        )
        return await _executar(session_id, conteudo, pedido["invocation_id"])


@api.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str):
    sessao = await _sessao(session_id)
    return [e.model_dump(mode="json", exclude_none=True, by_alias=True) for e in sessao.events]


@api.get("/apartamentos/{apartamento}/reservas")
def reservas_do_apartamento(apartamento: str):
    return db.reservas_do(apartamento)


@api.get("/apartamentos/{apartamento}/visitantes")
def visitantes_do_apartamento(apartamento: str):
    return db.visitantes_do(apartamento)
