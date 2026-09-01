"""Segredo da aplicação, hash de senha e controle de tentativas de login.

O segredo fica em `plenus_secret.key` (fora do git). Se não existir, é gerado na primeira
execução. Trocar esse arquivo desloga todo mundo.
"""

import os
import secrets
import time
from collections import defaultdict

from werkzeug.security import generate_password_hash, check_password_hash

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_ARQ_SEGREDO = os.path.join(_RAIZ, "plenus_secret.key")

SENHA_MIN = 8


def obter_secret_key():
    if os.path.exists(_ARQ_SEGREDO):
        try:
            with open(_ARQ_SEGREDO, encoding="utf-8") as f:
                valor = f.read().strip()
            if len(valor) >= 32:
                return valor
        except OSError:
            pass
    valor = secrets.token_hex(48)
    try:
        with open(_ARQ_SEGREDO, "w", encoding="utf-8") as f:
            f.write(valor)
        os.chmod(_ARQ_SEGREDO, 0o600)
    except OSError:
        pass
    return valor


def hash_senha(s):
    return generate_password_hash(s or "")


def senha_confere(s, h):
    try:
        return check_password_hash(h or "", s or "")
    except (ValueError, TypeError):
        return False


def problemas_senha(s):
    s = s or ""
    if len(s) < SENHA_MIN:
        return f"A senha precisa de pelo menos {SENHA_MIN} caracteres."
    if s.isdigit() or s.isalpha():
        return "Use letras e números na senha."
    return None


# ---------- throttle de login (em memória do processo) ----------

_JANELA_S = 300
_MAX_FALHAS = 5
_falhas = defaultdict(list)


def _limpar(chave):
    agora = time.time()
    _falhas[chave] = [t for t in _falhas[chave] if agora - t < _JANELA_S]


def bloqueado(chave):
    _limpar(chave)
    return len(_falhas[chave]) >= _MAX_FALHAS


def registrar_falha(chave):
    _limpar(chave)
    _falhas[chave].append(time.time())


def limpar_falhas(chave):
    _falhas.pop(chave, None)
