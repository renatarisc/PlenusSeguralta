"""Cópia do backup FORA do servidor: baixa para este computador o backup diário que a VPS
grava em /opt/plenus/backups_externos (cron das 02:30, `backup_db.py`).

Roda pela Tarefa Agendada do Windows "Plenus - baixar backup" (todo dia; se o PC estiver
desligado na hora, roda assim que ligar). Usa a chave SSH que já dá acesso à VPS.

    venv\\Scripts\\python.exe baixar_backup.py

Destino: %USERPROFILE%\\PlenusBackups (fora do OneDrive — o arquivo tem dados pessoais de
clientes). Mantém os 60 mais recentes. Troque com PLENUS_BACKUP_DESTINO / PLENUS_SSH.
"""

import os
import subprocess
import sys
from datetime import datetime

SSH = os.environ.get("PLENUS_SSH", "plenus@2.25.217.94")
REMOTO = "/opt/plenus/backups_externos"
DESTINO = os.environ.get("PLENUS_BACKUP_DESTINO",
                         os.path.join(os.path.expanduser("~"), "PlenusBackups"))
MANTER = 60
_SSH_OPC = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30"]


def _log(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linha)
    with open(os.path.join(DESTINO, "baixar_backup.log"), "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def _completo(caminho):
    """O mysqldump termina com '-- Dump completed'; arquivo cortado não conta como backup."""
    try:
        with open(caminho, "rb") as f:
            f.seek(max(0, os.path.getsize(caminho) - 300))
            return b"Dump completed" in f.read()
    except OSError:
        return False


def main():
    os.makedirs(DESTINO, exist_ok=True)
    r = subprocess.run(["ssh", *_SSH_OPC, SSH, f"ls -1t {REMOTO}/*.sql | head -1"],
                       capture_output=True, text=True, timeout=60)
    remoto = r.stdout.strip()
    if r.returncode or not remoto:
        _log(f"ERRO: não consegui listar os backups no servidor ({r.stderr.strip()})")
        return 1
    nome = os.path.basename(remoto)
    local = os.path.join(DESTINO, nome)
    if os.path.exists(local) and _completo(local):
        _log(f"já baixado: {nome}")
        return 0
    parcial = local + ".parcial"
    r = subprocess.run(["scp", *_SSH_OPC, f"{SSH}:{remoto}", parcial],
                       capture_output=True, text=True, timeout=600)
    if r.returncode or not _completo(parcial):
        _log(f"ERRO ao baixar {nome}: {r.stderr.strip() or 'arquivo incompleto'}")
        if os.path.exists(parcial):
            os.remove(parcial)
        return 1
    os.replace(parcial, local)
    _log(f"OK: {nome} ({os.path.getsize(local) / 1024:.0f} KB)")
    # rotação: só os .sql baixados por este script (plenus_AAAAMMDD_HHMMSS.sql)
    arqs = sorted(f for f in os.listdir(DESTINO) if f.startswith("plenus_") and f.endswith(".sql"))
    for f in arqs[:-MANTER]:
        os.remove(os.path.join(DESTINO, f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
