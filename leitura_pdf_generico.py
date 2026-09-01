"""Leitura genérica de PDF de apólice — reserva para quando o layout não é reconhecido.

Proposital: é CONSERVADOR. Só devolve o que dá pra afirmar com segurança (CPF com dígito
verificador, e-mail, datas/valores colados no rótulo certo). Não tenta adivinhar nome e
endereço sem uma âncora forte — preencher errado é pior do que deixar em branco.
"""

import re

from validacao import cpf_valido, para_decimal, formatar_numero, so_digitos

_DATA = r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
_MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def _norm(t):
    return "\n".join(re.sub(r"[ \t ]+", " ", l).strip() for l in (t or "").splitlines() if l.strip())


def _data_iso(bruto):
    if not bruto:
        return None
    m = re.search(_DATA, bruto)
    if not m:
        return None
    d, mes, a = re.split(r"[/.\-]", m.group(0))
    a = a if len(a) == 4 else ("20" + a if int(a) < 70 else "19" + a)
    try:
        d, mes, a = int(d), int(mes), int(a)
        return f"{a:04d}-{mes:02d}-{d:02d}" if 1 <= d <= 31 and 1 <= mes <= 12 else None
    except ValueError:
        return None


def _dinheiro(bruto):
    v = para_decimal(bruto)
    return formatar_numero(v) if v is not None else None


def _achar(t, padrao, grupo=1):
    m = re.search(padrao, t, re.I)
    return m.group(grupo).strip() if m else None


# ---------------------------------------------------------------- cliente

def extrair_campos_cliente(texto):
    t = _norm(texto)
    c = {}

    for m in re.finditer(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b", t):
        if cpf_valido(m.group(1)):
            c["cpf"] = so_digitos(m.group(1))
            break

    email = _achar(t, r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
    if email and not re.search(r"(susep|ouvidoria|sac|atendimento|seguros?\.com|dpo@)", email, re.I):
        c["email"] = email.lower()

    nasc = _achar(t, r"nascimento[^\n\d]{0,20}(" + _DATA + r")")
    if _data_iso(nasc):
        c["data_nascimento"] = _data_iso(nasc)

    tel = _achar(t, r"(?:telefone|tel\.?|fone|celular)[^\n\d]{0,15}(\(?\d{2,3}\)?[ .\-]?\d{4,5}[ .\-]?\d{4})")
    if tel:
        mm = re.search(r"\(?(\d{2,3})\)?[ .\-]?(\d{4,5})[ .\-]?(\d{4})", tel)
        if mm:
            ddd = mm.group(1)
            c["tel_ddd"] = ddd[1:] if len(ddd) == 3 and ddd[0] == "0" else ddd[:2]
            c["tel_numero"] = mm.group(2) + mm.group(3)

    # nome/endereço: só com rótulo explícito e valor logo em seguida na MESMA linha
    nome = _achar(t, r"nome\s+(?:completo\s+)?(?:do\s+)?(?:segurad[oa]|client[e])\s*[:\-]\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ '.\-]{5,60})")
    if nome and " " in nome:
        c["nome"] = nome.title() if nome.isupper() else nome

    cep = _achar(t, r"\bcep\s*[:\-]?\s*(\d{5}-?\d{3})")
    if cep:
        c["end_cep"] = so_digitos(cep)

    return c


# ---------------------------------------------------------------- apólice

def extrair_campos_apolice(texto):
    t = _norm(texto)
    c = {}

    numero = _achar(t, r"(?:n[ºo°]?\s*d[ao]\s*)?ap[óo]lice\s*(?:n[ºo°]?\.?)?\s*[:\-]?\s*([0-9][0-9A-Za-z.\-/]{4,})") \
        or _achar(t, r"proposta\s*(?:n[ºo°]?\.?)?\s*[:\-]?\s*([0-9][0-9A-Za-z.\-/]{4,})")
    if numero:
        c["numero_apolice"] = numero.strip(" .-")

    janela = _achar(t, r"vig[êe]ncia(.{0,200})", flags=0) if False else None
    m = re.search(r"vig[êe]ncia(.{0,200})", t, re.I | re.S)
    dv = re.findall(_DATA, m.group(1)) if m else []
    ini = _achar(t, r"in[íi]cio[^\n\d]{0,15}(" + _DATA + r")")
    fim = _achar(t, r"(?:fim|t[ée]rmino)[^\n\d]{0,15}(" + _DATA + r")")
    vi = _data_iso(ini) or (_data_iso(dv[0]) if dv else None)
    vf = _data_iso(fim) or (_data_iso(dv[1]) if len(dv) > 1 else None)
    if vi:
        c["vigencia_inicio"] = vi
    if vf:
        c["vigencia_fim"] = vf

    premio = _achar(t, r"pr[êe]mio\s*l[íi]quido[^\n\d]{0,20}(" + _MOEDA + r")")
    if _dinheiro(premio):
        c["premio_liquido"] = _dinheiro(premio)
    iof = _achar(t, r"\biof\b[^\n\d]{0,20}(" + _MOEDA + r")")
    if _dinheiro(iof):
        c["iof"] = _dinheiro(iof)
    total = _achar(t, r"pr[êe]mio\s*total[^\n\d]{0,20}(" + _MOEDA + r")")
    if _dinheiro(total):
        c["premio_total"] = _dinheiro(total)

    pct = _achar(t, r"comiss[ãa]o[^\n%]{0,20}?(\d{1,3}(?:[.,]\d{1,2})?)\s*%") \
        or _achar(t, r"comiss[ãa]o\s*\(%\)[^\n\d]{0,15}(\d{1,3}(?:[.,]\d{1,2})?)")
    if pct:
        c["comissao_percentual"] = pct.replace(".", ",")
    cval = _achar(t, r"comiss[ãa]o[^\n]{0,20}?R\$\s*(" + _MOEDA + r")")
    if _dinheiro(cval):
        c["comissao_valor_seguralta_receber"] = _dinheiro(cval)

    # veículo (seguro de automóvel)
    placa = _achar(t, r"placa[^A-Z0-9]{0,10}([A-Z]{3}[- ]?\d[A-Z0-9]\d{2})") \
        or _achar(t, r"\b([A-Z]{3}[- ]?\d[A-Z0-9]\d{2})\b")
    if placa:
        c["veiculo_placa"] = re.sub(r"[ \-]", "", placa).upper()
    veic = _achar(t, r"(?:ve[íi]culo|marca\s*/?\s*modelo|modelo)\s*[:\-]\s*([A-Za-z0-9À-ÿ /.\-]{4,60})")
    if veic:
        c["veiculo_descricao"] = veic.strip(" .-")

    c["parcelas"] = _parcelas(t)
    return c


def _parcelas(t):
    out = []
    for m in re.finditer(r"(?m)^\s*(\d{1,2})\s*[/xª\-]\s*(\d{1,2})\b[^\n]*?(" + _DATA + r")?[^\n]*?(" + _MOEDA + r")", t):
        i, tot, data, valor = m.groups()
        out.append({"identificacao": f"{int(i)}/{int(tot)}", "data": _data_iso(data) if data else None,
                    "valor": _dinheiro(valor)})
    if out:
        return out
    for m in re.finditer(r"(?i)parcela\s*(\d{1,2})?[^\n]*?(" + _DATA + r")[^\n]*?(" + _MOEDA + r")", t):
        i, data, valor = m.groups()
        out.append({"identificacao": (i or None), "data": _data_iso(data), "valor": _dinheiro(valor)})
    if out:
        seq = [p["identificacao"] for p in out]
        if all(x and x.isdigit() for x in seq) and [int(x) for x in seq] == list(range(1, len(seq) + 1)):
            for k, p in enumerate(out, 1):
                p["identificacao"] = f"{k}/{len(out)}"
        return out
    m = re.search(r"\b(\d{1,2})\s*x\s*(?:de\s*)?R?\$?\s*(" + _MOEDA + r")", t, re.I)
    if m:
        n, valor = int(m.group(1)), _dinheiro(m.group(2))
        out = [{"identificacao": f"{k}/{n}", "data": None, "valor": valor} for k in range(1, n + 1)]
    return out
