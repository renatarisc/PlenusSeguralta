"""Copia consistente do banco `plenus` (MySQL) para um arquivo .sql unico.

Usa `mysqldump --single-transaction` (snapshot consistente do InnoDB mesmo com o sistema
em uso). Serve para o backup que sai da maquina (cron/Agendador + rclone/restic, ou
snapshot do provedor).

    python backup_db.py [destino.sql]

Sem argumento, grava em  backups_externos/plenus_AAAAMMDD_HHMMSS.sql  e mantem os 30 mais
recentes. Com argumento, grava exatamente nesse caminho (sem rotacao).
"""

import os
import subprocess
import sys
from datetime import datetime

from db import config_db, _mysqldump_bin

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_PASTA = os.path.join(_RAIZ, "backups_externos")
_MANTER = 30


def copiar(destino):
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    dump = _mysqldump_bin()
    if not dump:
        raise RuntimeError("mysqldump nao encontrado no PATH nem em 'C:\\Program Files\\MySQL\\...'")
    cfg = config_db()
    cmd = [dump, "--host", str(cfg["host"]), "--port", str(cfg["port"]),
           "--user", str(cfg["user"]), "--no-tablespaces", "--skip-lock-tables",
           str(cfg["database"])]
    env = {**os.environ, "MYSQL_PWD": str(cfg.get("password") or "")}
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env, check=True, timeout=300)
    return destino


def _rotacionar():
    if not os.path.isdir(_PASTA):
        return
    arqs = sorted(f for f in os.listdir(_PASTA) if f.endswith(".sql"))
    for f in arqs[:-_MANTER]:
        try:
            os.remove(os.path.join(_PASTA, f))
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("Backup gravado em:", copiar(sys.argv[1]))
    else:
        nome = f"plenus_{datetime.now():%Y%m%d_%H%M%S}.sql"
        print("Backup gravado em:", copiar(os.path.join(_PASTA, nome)))
        _rotacionar()
