"""Restaura reservas e visitantes ao estado de dados/ e apaga as sessões.

Uso: uv run python -m aurora.restaurar  (com a API parada)
"""

from . import db

if __name__ == "__main__":
    try:
        db.restaurar()
    except PermissionError:
        raise SystemExit("Os arquivos estão em uso. Pare a API (Ctrl+C) e rode o comando de novo.")
    print("Dados restaurados.")
