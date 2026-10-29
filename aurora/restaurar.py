"""Restaura reservas e visitantes ao estado de dados/ e apaga as sessões.

Uso: uv run python -m aurora.restaurar  (com a API parada)
"""

from . import db

if __name__ == "__main__":
    db.restaurar()
    print("Dados restaurados.")
