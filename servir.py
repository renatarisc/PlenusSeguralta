"""Servidor de produção do Plenus (waitress).

Use ISTO no computador que vai compartilhar o sistema — não o `python app.py`
(aquele é o servidor de desenvolvimento, com debug ligado).

    venv\\Scripts\\python.exe servir.py

Fica ouvindo em http://0.0.0.0:5000 (todas as interfaces, inclusive a do Tailscale).
Ctrl+C para parar.
"""

from waitress import serve

from app import app

if __name__ == "__main__":
    porta = 5000
    print(f"Plenus no ar em http://0.0.0.0:{porta}  (Ctrl+C para parar)")
    serve(app, host="0.0.0.0", port=porta, threads=8)
