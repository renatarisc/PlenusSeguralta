"""Validação e normalização dos campos com regra própria (CPF, CEP, e-mail, telefone).

Roda no servidor - a validação no navegador (static/js/app.js) é só conforto, aqui é a que vale.
Guarda sempre só os dígitos (sem máscara) no banco; a máscara é aplicada só na exibição.
"""

import re

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def so_digitos(texto):
    return re.sub(r"\D", "", texto or "")


# ---------- CPF ----------

def cpf_valido(cpf):
    d = so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for tam in (9, 10):
        soma = sum(int(d[i]) * ((tam + 1) - i) for i in range(tam))
        dig = (soma * 10) % 11
        dig = 0 if dig == 10 else dig
        if dig != int(d[tam]):
            return False
    return True


def formatar_cpf(cpf):
    d = so_digitos(cpf)
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}" if len(d) == 11 else (cpf or "")


# ---------- CEP ----------

def cep_valido(cep):
    return len(so_digitos(cep)) == 8


def formatar_cep(cep):
    d = so_digitos(cep)
    return f"{d[0:5]}-{d[5:8]}" if len(d) == 8 else (cep or "")


# ---------- e-mail ----------

def email_valido(email):
    return bool(_RE_EMAIL.match((email or "").strip()))


# ---------- telefone ----------

def formatar_telefone(ddd, numero):
    ddd, numero = so_digitos(ddd), so_digitos(numero)
    if not (ddd or numero):
        return ""
    if len(numero) == 9:
        numero = f"{numero[0:5]}-{numero[5:9]}"
    elif len(numero) == 8:
        numero = f"{numero[0:4]}-{numero[4:8]}"
    return f"({ddd}) {numero}" if ddd else numero


# ---------- validação do formulário de cliente ----------

def validar_cliente(dados):
    # dados: dict com os campos crus do form (já com só dígitos onde faz sentido).
    # Devolve lista de mensagens de erro (vazia = ok).
    erros = []
    if not (dados.get("nome") or "").strip():
        erros.append("Nome é obrigatório.")
    cpf = dados.get("cpf")
    if cpf and not cpf_valido(cpf):
        erros.append("CPF inválido.")
    cep = dados.get("end_cep")
    if cep and not cep_valido(cep):
        erros.append("CEP deve ter 8 dígitos.")
    email = dados.get("email")
    if email and not email_valido(email):
        erros.append("E-mail em formato inválido.")
    return erros
