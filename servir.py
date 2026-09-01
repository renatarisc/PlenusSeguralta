"""Servidor de produção do Plenus (waitress).

Use ISTO no computador que vai compartilhar o sistema — não o `python app.py`
(aquele é o servidor de desenvolvimento, com debug ligado).

    venv\\Scripts\\python.exe servir.py

Fica ouvindo em http://0.0.0.0:5000 (todas as interfaces, inclusive a do Tailscale).
Ctrl+C para parar.
"""

import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.environ.get("PLENUS_BIND", "0.0.0.0")   # no VPS use 127.0.0.1 (só o proxy alcança)
    porta = int(os.environ.get("PLENUS_PORTA", "5000"))
    threads = int(os.environ.get("PLENUS_THREADS", "8"))
    print(f"Plenus no ar em http://{host}:{porta}  ({threads} threads, Ctrl+C para parar)")
    serve(app, host=host, port=porta, threads=threads, ident="Plenus")
