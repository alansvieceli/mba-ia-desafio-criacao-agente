"""Consulta ao regulamento por trechos: nunca devolve o texto inteiro.

O regulamento é dividido em artigos. Cada pergunta ranqueia os artigos e devolve
só os melhores de UM capítulo, o do artigo mais relevante, para que nenhum
trecho de assunto alheio entre na sessão.
"""

import math
import re
import unicodedata

from .db import DADOS

_PARADAS = {
    "que", "qual", "quais", "como", "para", "por", "com", "sem", "uma", "uns", "umas", "das", "dos",
    "nas", "nos", "pelo", "pela", "ate", "ser", "tem", "sao", "esta", "esse", "essa", "isso", "mais",
    "pode", "posso", "podem", "quando", "onde", "existe", "aos", "num", "numa", "meu", "minha",
}


def _tokens(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    palavras = re.findall(r"[a-z0-9]{3,}", texto)
    # tira o plural simples, para "domingos" casar com "domingo"
    return {p[:-1] if len(p) > 4 and p.endswith("s") else p for p in palavras if p not in _PARADAS}


def _carregar():
    artigos, capitulo = [], ""
    for bloco in (DADOS / "regulamento.md").read_text(encoding="utf-8").split("\n\n"):
        bloco = bloco.strip()
        if bloco.startswith("## "):
            capitulo = bloco[3:]
        elif bloco.startswith("**Art."):
            artigos.append({"capitulo": capitulo, "texto": bloco})
        elif artigos and bloco and not bloco.startswith("#"):
            artigos[-1]["texto"] += "\n\n" + bloco  # incisos e parágrafos do mesmo artigo
    for a in artigos:
        a["tokens"] = _tokens(a["texto"])
        a["titulo"] = _tokens(a["capitulo"])
    return artigos


_ARTIGOS = _carregar()
_FREQ = {t: sum(t in a["tokens"] | a["titulo"] for a in _ARTIGOS) for a in _ARTIGOS for t in a["tokens"] | a["titulo"]}


def _peso(token):
    return math.log(1 + len(_ARTIGOS) / _FREQ[token])


def consultar(pergunta, maximo=4):
    """Devolve os artigos mais relevantes do capítulo mais relevante, ou ''."""
    consulta = {t for t in _tokens(pergunta) if t in _FREQ}
    # casar com o título do capítulo vale o dobro: "mudança" leva ao capítulo Mudanças
    notas = [
        (sum(_peso(t) for t in consulta & a["tokens"]) + 2 * sum(_peso(t) for t in consulta & a["titulo"]), a)
        for a in _ARTIGOS
    ]
    melhor = max(notas, key=lambda n: n[0])
    if melhor[0] == 0:
        return ""
    do_capitulo = sorted(
        (n for n in notas if n[1]["capitulo"] == melhor[1]["capitulo"] and n[0] >= melhor[0] / 2),
        key=lambda n: -n[0],
    )[:maximo]
    return f"{melhor[1]['capitulo']}\n\n" + "\n\n".join(a["texto"] for _, a in do_capitulo)
