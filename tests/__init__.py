"""Testes automáticos do Plenus — rodam SÓ no banco separado `plenus_teste`.

    venv\\Scripts\\python.exe -m unittest discover -s tests -v

Preparação (uma vez, como root do MySQL):
    CREATE DATABASE plenus_teste CHARACTER SET utf8mb4;
    GRANT ALL PRIVILEGES ON plenus_teste.* TO 'plenus'@'localhost';

A cada execução as tabelas do plenus_teste são recriadas do zero. Uma trava impede rodar
contra qualquer banco cujo nome não termine em `_teste` (os dados reais ficam no `plenus`).
"""

import os

os.environ.setdefault("PLENUS_DB_DATABASE", "plenus_teste")
if not os.environ["PLENUS_DB_DATABASE"].endswith("_teste"):
    raise SystemExit("Testes só rodam num banco *_teste (PLENUS_DB_DATABASE="
                     f"{os.environ['PLENUS_DB_DATABASE']!r}).")
