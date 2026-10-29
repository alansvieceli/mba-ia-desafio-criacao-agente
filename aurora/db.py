"""Armazenamento do condomínio em SQLite: reservas e visitantes."""

import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
ESTADO = RAIZ / "estado"
BANCO = ESTADO / "condominio.db"
BANCO_SESSOES = ESTADO / "sessoes.db"

# A exclusividade (uma reserva ativa por área e data) vive no índice único:
# é o próprio banco que recusa a segunda gravação, mesmo em disputa simultânea.
ESQUEMA = """
CREATE TABLE IF NOT EXISTS reservas (
    codigo TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area TEXT NOT NULL,
    data TEXT NOT NULL,
    ativa INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reserva_ativa ON reservas (area, data) WHERE ativa = 1;
CREATE TABLE IF NOT EXISTS visitantes (
    apartamento TEXT NOT NULL,
    nome TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE (apartamento, nome, data)
);
"""


def _json(nome):
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


def areas():
    return {a["id"]: a for a in _json("areas.json")}


def apartamentos():
    return {a["numero"] for a in _json("apartamentos.json")}


@contextmanager
def _conectar():
    ESTADO.mkdir(exist_ok=True)
    db = sqlite3.connect(BANCO, timeout=30, isolation_level=None)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        yield db
    finally:
        db.close()


def iniciar():
    """Cria o banco com os dados iniciais, se ainda não existir."""
    with _conectar() as db:
        novo = not db.execute("SELECT 1 FROM sqlite_master WHERE name='reservas'").fetchone()
        db.executescript(ESQUEMA)
        if novo:
            db.executemany(
                "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
                [(r["codigo"], r["apartamento"], r["area"], r["data"]) for r in _json("reservas.json")],
            )
            db.executemany(
                "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                [(v["apartamento"], v["nome"], v["data"]) for v in _json("visitantes.json")],
            )


def restaurar():
    """Volta reservas e visitantes ao estado de dados/ e apaga as sessões."""
    for base in (BANCO, BANCO_SESSOES):
        for sufixo in ("", "-wal", "-shm"):
            Path(str(base) + sufixo).unlink(missing_ok=True)
    iniciar()


def reservas_do(apartamento):
    with _conectar() as db:
        linhas = db.execute(
            "SELECT codigo, area, data FROM reservas WHERE apartamento=? AND ativa=1 ORDER BY data, codigo",
            (apartamento,),
        )
        return [{"codigo": c, "area": a, "data": d} for c, a, d in linhas]


def visitantes_do(apartamento):
    with _conectar() as db:
        linhas = db.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento=? ORDER BY data, nome", (apartamento,)
        )
        return [{"nome": n, "data": d} for n, d in linhas]


def area_livre(area, data):
    with _conectar() as db:
        return db.execute(
            "SELECT 1 FROM reservas WHERE area=? AND data=? AND ativa=1", (area, data)
        ).fetchone() is None


def reservar(apartamento, area, data):
    """Grava a reserva e devolve o código, ou None se a data já está ocupada."""
    with _conectar() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            while True:
                codigo = f"RSV-{secrets.randbelow(9000) + 1000}"
                # inclui reservas canceladas: um código nunca é reaproveitado
                if not db.execute("SELECT 1 FROM reservas WHERE codigo=?", (codigo,)).fetchone():
                    break
            db.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
                (codigo, apartamento, area, data),
            )
        except sqlite3.IntegrityError:
            db.execute("ROLLBACK")
            return None
        db.execute("COMMIT")
        return codigo


def cancelar(apartamento, codigo="", area="", data=""):
    """Cancela uma reserva ativa do apartamento. Devolve o código ou None."""
    with _conectar() as db:
        db.execute("BEGIN IMMEDIATE")
        achada = db.execute(
            "SELECT codigo FROM reservas WHERE apartamento=? AND ativa=1 AND (codigo=? OR (area=? AND data=?))",
            (apartamento, codigo, area, data),
        ).fetchone()
        if achada:
            db.execute("UPDATE reservas SET ativa=0 WHERE codigo=?", achada)
        db.execute("COMMIT")
        return achada[0] if achada else None


def autorizar_visitante(apartamento, nome, data):
    with _conectar() as db:
        db.execute(
            "INSERT OR IGNORE INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
