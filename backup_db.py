"""Cópia consistente do banco para um arquivo único (mesmo com o sistema em uso).

Usa a API de backup online do SQLite — seguro mesmo com gravações acontecendo.
Serve para o backup que sai da máquina (cron + rclone/restic, ou snapshot do provedor).

    python backup_db.py [destino]

Sem argumento, grava em  backups_externos/plenus_AAAAMMDD_HHMMSS.db  e mantém os 30 mais
recentes. Com argumento, grava exatamente nesse caminho (sem rotação).
"""

import os
import sqlite3
import sys
from datetime import datetime

from db import CAMINHO_DB

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_PASTA = os.path.join(_RAIZ, "backups_externos")
_MANTER = 30


def copiar(destino):
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    origem = sqlite3.connect(CAMINHO_DB)
    try:
        alvo = sqlite3.connect(destino)
        with alvo:
            origem.backup(alvo)
        alvo.close()
    finally:
        origem.close()
    return destino


def _rotacionar():
    if not os.path.isdir(_PASTA):
        return
    arqs = sorted(f for f in os.listdir(_PASTA) if f.endswith(".db"))
    for f in arqs[:-_MANTER]:
        try:
            os.remove(os.path.join(_PASTA, f))
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("Backup gravado em:", copiar(sys.argv[1]))
    else:
        nome = f"plenus_{datetime.now():%Y%m%d_%H%M%S}.db"
        print("Backup gravado em:", copiar(os.path.join(_PASTA, nome)))
        _rotacionar()
