"""Validação e normalização dos campos com regra própria (CPF, CEP, e-mail, telefone).

Roda no servidor - a validação no navegador (static/js/app.js) é só conforto, aqui é a que vale.
Guarda sempre só os dígitos (sem máscara) no banco; a máscara é aplicada só na exibição.
"""

import re
from datetime import date
from itertools import zip_longest

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


# ---------- números / moeda / data (usados na apólice) ----------

def para_decimal(texto):
    """'1.234,56', '1234,56' ou '1234.56' -> float. Vazio -> None. Inválido -> None."""
    if isinstance(texto, (int, float)):
        return float(texto)
    s = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:                       # formato brasileiro: ponto é milhar, vírgula é decimal
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _numero_preenchido_invalido(texto):
    return bool((texto or "").strip()) and para_decimal(texto) is None


def formatar_numero(v, casas=2):
    """float -> '1.234,56' (pt-BR). None/'' -> ''."""
    d = para_decimal(v) if not isinstance(v, (int, float)) else float(v)
    if d is None:
        return ""
    txt = f"{d:,.{casas}f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_moeda(v):
    txt = formatar_numero(v)
    return f"R$ {txt}" if txt else "—"


def formatar_data_br(iso):
    s = (iso or "").strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
    return s or "—"


def dias_ate_data(iso):
    """Dias entre hoje e a data ISO (negativo = já passou). None se não for data válida."""
    s = (iso or "").strip()[:10]
    try:
        alvo = date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, IndexError):
        return None
    return (alvo - date.today()).days


# ---------- parcelas da apólice ----------

def preparar_parcelas(identificacoes, datas, valores, pagas=None):
    """Recebe listas paralelas (request.form.getlist). Ignora linhas totalmente vazias.
    Devolve (parcelas, erros) — dict {identificacao, data, valor(float|None), paga(0/1)}."""
    parcelas, erros = [], []
    linhas = zip_longest(identificacoes or [], datas or [], valores or [], pagas or [], fillvalue="")
    n = 0
    for ident, data, valor, paga in linhas:
        ident = (ident or "").strip()
        data = (data or "").strip()
        valor_txt = (valor or "").strip()
        if not (ident or data or valor_txt):
            continue
        n += 1
        v = para_decimal(valor_txt)
        if valor_txt and v is None:
            erros.append(f"Parcela {n}: valor numérico inválido.")
        parcelas.append({
            "identificacao": ident or None, "data": data or None, "valor": v,
            "paga": 1 if str(paga).strip() in ("1", "sim", "on", "true") else 0,
        })
    return parcelas, erros


# ---------- validação do formulário de apólice ----------

def validar_apolice(dados):
    erros = []
    if not (dados.get("cliente_id") or "").strip():
        erros.append("Selecione o cliente.")
    if not (dados.get("tipo_seguro_id") or "").strip():
        erros.append("Selecione o tipo de seguro.")
    if not (dados.get("numero_apolice") or "").strip():
        erros.append("Informe o número da apólice.")

    ini = (dados.get("vigencia_inicio") or "").strip()
    fim = (dados.get("vigencia_fim") or "").strip()
    if ini and fim and fim < ini:
        erros.append("O fim da vigência é anterior ao início.")

    for campo, rotulo in (("premio_liquido", "Prêmio líquido"),
                          ("iof", "IOF"),
                          ("premio_total", "Prêmio total"),
                          ("comissao_percentual", "Comissão (%)"),
                          ("comissao_valor", "Comissão (valor)")):
        if _numero_preenchido_invalido(dados.get(campo)):
            erros.append(f"{rotulo}: valor numérico inválido.")

    pct = para_decimal(dados.get("comissao_percentual"))
    if pct is not None and not (0 <= pct <= 100):
        erros.append("Comissão (%) deve ficar entre 0 e 100.")

    return erros


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
