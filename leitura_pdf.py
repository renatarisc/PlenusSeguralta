"""Lê um PDF de apólice e tenta extrair os campos do cadastro (cliente e apólice).

Cada seguradora gera o PDF de um jeito. O PyMuPDF costuma devolver TODOS os rótulos e depois
TODOS os valores (são células de tabela), então "Rótulo: valor" na mesma linha quase nunca
funciona. A estratégia aqui:

  1. extrai o texto (OCR se o PDF for digitalizado);
  2. reconhece a seguradora pelo cabeçalho/rodapé e usa um parser feito sob medida para o
     layout dela (hoje: Yelum e SulAmérica);
  3. o que não for reconhecido cai num parser genérico de melhor-esforço.

Nada é salvo automaticamente — o resultado só pré-preenche o formulário pra conferência.
"""

import io
import os
import re

import pymupdf  # PyMuPDF

from validacao import cpf_valido, para_decimal, formatar_numero, so_digitos

_TESSERACT_PADRAO = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

_MAX_PAGINAS_OCR = 6
_MIN_TEXTO_UTIL = 120

_DATA = r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
_RE_CPF = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RE_FORMA_PGTO = re.compile(
    r"(cart[ãa]o de cr[ée]dito|d[ée]bito em conta|d[ée]bito autom[áa]tico|boleto banc[áa]rio|"
    r"boleto|carn[êe]|pix|d[ée]bito|folha de pagamento|dinheiro|à vista|a vista)", re.I)


# ---------------------------------------------------------------- extração de texto

def extrair_texto(pdf_bytes):
    """Devolve (texto, origem) com origem em {'texto', 'ocr', 'vazio'}."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return "", "vazio"
    with doc:
        texto = "\n".join(p.get_text("text") for p in doc).strip()
        if len(texto) >= _MIN_TEXTO_UTIL:
            return texto, "texto"
        ocr = _ocr_documento(doc).strip()
        if len(ocr) >= max(len(texto), _MIN_TEXTO_UTIL // 2):
            return ocr, "ocr"
        return texto, ("texto" if texto else "vazio")


def _ocr_documento(doc):
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return ""
    if os.path.exists(_TESSERACT_PADRAO):
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PADRAO
    linguas = "por"
    try:
        if "por" not in pytesseract.get_languages(config=""):
            linguas = "eng"
    except Exception:
        pass
    saidas = []
    for pag in list(doc)[:_MAX_PAGINAS_OCR]:
        try:
            pix = pag.get_pixmap(dpi=300)
            saidas.append(pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))),
                                                      lang=linguas))
        except Exception:
            continue
    return "\n".join(saidas)


# ---------------------------------------------------------------- utilidades de linha

def _linhas(texto):
    return [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in (texto or "").splitlines() if l.strip()]


def _idx(linhas, *alvos, inicio=0):
    for i in range(max(inicio, 0), len(linhas)):
        baixo = linhas[i].lower()
        if any(a.lower() in baixo for a in alvos):
            return i
    return -1


def _apos(linhas, rotulo, cond, limite=15, inicio=0):
    """1ª linha depois de `rotulo` (a partir de `inicio`) que satisfaz cond(linha)."""
    i = _idx(linhas, rotulo, inicio=inicio)
    if i < 0:
        return None
    for l in linhas[i + 1:i + 1 + limite]:
        if cond(l):
            return l
    return None


def _e_data(l):
    return bool(re.fullmatch(_DATA, l))


def _e_dinheiro(l):
    return bool(re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}", l))


def _e_inteiro(l):
    return bool(re.fullmatch(r"\d{1,3}", l))


def _parece_nome(l):
    if not (6 <= len(l) <= 70) or " " not in l:
        return False
    if not re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'\-]+", l):
        return False
    ruins = ("segurad", "cnpj", "cpf", "corretor", "endere", "bairro", "cidade", "emiss",
             "propon", "obriga", "seguro", "condi", "vig[êe]ncia", "susep", "ramo", r"\bnome\b",
             "social", "pagamento", "cobertura", "pr[êe]mio", "passaporte", "expedi")
    return not any(re.search(r, l.lower()) for r in ruins)


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
        if not (1 <= d <= 31 and 1 <= mes <= 12):
            return None
        return f"{a:04d}-{mes:02d}-{d:02d}"
    except ValueError:
        return None


def _dinheiro(bruto):
    v = para_decimal(bruto)
    return formatar_numero(v) if v is not None else None


def _titulo(nome):
    if not nome:
        return None
    n = nome.strip()
    if n.isupper() or n.islower():
        n = n.title()
    return re.sub(r"\b(Da|De|Do|Das|Dos|E)\b", lambda m: m.group(1).lower(), n)


def _primeiro_cpf(texto, exigir_dv=True):
    for m in _RE_CPF.finditer(texto):
        if not exigir_dv or cpf_valido(m.group(1)):
            return so_digitos(m.group(1))
    return None


def _tel_partes(bruto):
    m = re.search(r"\(?(\d{2,3})\)?[ .\-]?(\d{4,5})[ .\-]?(\d{4})", bruto or "")
    if not m:
        return {}
    ddd = m.group(1)
    ddd = ddd[1:] if len(ddd) == 3 and ddd[0] == "0" else ddd[:2]
    return {"tel_ddd": ddd, "tel_numero": m.group(2) + m.group(3)}


def _forma_pgto(texto):
    m = _RE_FORMA_PGTO.search(texto or "")
    if not m:
        return None
    achado = m.group(1).lower()
    if "cart" in achado:
        return "Cartão de Crédito"
    if "boleto" in achado:
        return "Boleto"
    if "pix" in achado:
        return "Pix"
    if "d\u00e9bito" in achado or "debito" in achado:
        return "Débito em conta"
    if "carn" in achado:
        return "Carnê"
    if "vista" in achado:
        return "À vista"
    if "folha" in achado:
        return "Folha de pagamento"
    return achado.capitalize()


def _endereco_por_travessao(val):
    """'RUA X - 650 - BAIRRO - CIDADE - RJ - 28051-287' -> dict de end_*"""
    partes = [p.strip() for p in re.split(r"\s+-\s+", val) if p.strip()]
    if len(partes) < 3:
        return {}
    c = {}
    if re.fullmatch(r"\d{5}-?\d{3}", partes[-1]):
        c["end_cep"] = so_digitos(partes.pop())
    if partes and partes[-1].upper() in _UFS:
        c["end_estado"] = partes.pop().upper()
    if partes:
        c["end_cidade"] = _titulo(partes.pop())
    if partes:
        c["end_bairro"] = _titulo(partes.pop())
    if partes:
        c["end_rua"] = _titulo(partes[0])
    if len(partes) > 1 and re.fullmatch(r"\d+[A-Za-z]?", partes[1]):
        c["end_numero"] = partes[1]
    elif len(partes) > 1:
        c["end_complemento"] = partes[1]
    return c


# ---------------------------------------------------------------- Yelum

def _e_yelum(texto):
    t = texto.lower()
    return "yelum seguros" in t or "yelumseguros" in t


def _parse_yelum(linhas, texto, alvo):
    c = {}
    fim_seg = _idx(linhas, "DADOS DO CORRETOR")
    fim_seg = fim_seg if fim_seg > 0 else len(linhas)

    if alvo == "cliente":
        i_nome = _idx(linhas, "Nome do(a) Segurado")
        if 0 <= i_nome < fim_seg:
            for l in linhas[i_nome + 1:fim_seg]:
                if _parece_nome(l):
                    c["nome"] = _titulo(l)
                    break
        cpf = _primeiro_cpf(texto) or _primeiro_cpf(texto, exigir_dv=False)
        if cpf:
            c["cpf"] = cpf

        i_end = _idx(linhas, "Endereço", inicio=_idx(linhas, "DADOS DO(A) SEGURADO"))
        if 0 <= i_end < fim_seg and i_end + 1 < len(linhas):
            m = re.match(r"(.+?),?\s*(\d+[A-Za-z]?)$", linhas[i_end + 1])
            if m:
                c["end_rua"], c["end_numero"] = _titulo(m.group(1)), m.group(2)
            else:
                c["end_rua"] = _titulo(linhas[i_end + 1])

        for i in range(len(linhas) - 5):
            if linhas[i] == "Bairro" and linhas[i + 1] == "CEP" and linhas[i + 2] == "Cidade":
                c["end_bairro"] = _titulo(linhas[i + 3])
                if re.fullmatch(r"\d{5}-?\d{3}", linhas[i + 4]):
                    c["end_cep"] = so_digitos(linhas[i + 4])
                c["end_cidade"] = _titulo(linhas[i + 5])
                break
        for i in range(len(linhas) - 4):
            if linhas[i] == "UF" and linhas[i + 1].lower().startswith("telefone"):
                if linhas[i + 4] in _UFS:
                    c["end_estado"] = linhas[i + 4]
                for l in linhas[i + 4:i + 8]:
                    p = _tel_partes(l)
                    if p:
                        c.update(p)
                        break
                break
        email = _RE_EMAIL.search("\n".join(linhas[:fim_seg]))
        if email:
            c["email"] = email.group(0).lower()
        return c

    # ---- apólice ----
    m = re.search(r"\b(\d{2}-\d{2}-\d{4}\.\d{6,8})\b", texto)
    if m:
        c["numero_apolice"] = m.group(1)
    m = re.search(r"de\s+(" + _DATA + r")\s+às\s+24\s*horas?\s+de\s+(" + _DATA + r")", texto, re.I)
    if m:
        c["vigencia_inicio"] = _data_iso(m.group(1))
        c["vigencia_fim"] = _data_iso(m.group(2))
    m = re.search(r"Pr[êe]mio L[íi]quido(?: do Item)?[:\s]*\n?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", texto, re.I)
    pl = m.group(1) if m else _apos(linhas, "Prêmio Líquido", _e_dinheiro)
    if _dinheiro(pl):
        c["premio_liquido"] = _dinheiro(pl)

    fp = _forma_pgto(texto)
    if fp:
        c["forma_pagamento"] = fp
    if _e_yelum(texto):
        c["seguradora"] = "Yelum Seguros"
    mr = re.search(r"Ramo\s+\d+\s*-\s*([A-ZÀ-Ú][A-ZÀ-Ú /]+)", texto)
    if mr:
        c["tipo_seguro"] = _titulo(mr.group(1).strip())

    # parcelas: nº de parcelas + (vencimento, valor) do bloco PARCELAMENTO
    qtd = _apos(linhas, "Número de Parcelas", _e_inteiro) or "1"
    qtd = int(qtd) if qtd.isdigit() and int(qtd) > 0 else 1
    ip = _idx(linhas, "PARCELAMENTO")
    venc = valor = None
    if ip >= 0:
        for l in linhas[ip:ip + 20]:
            if not venc and _e_data(l):
                venc = _data_iso(l)
            elif venc and not valor and _e_dinheiro(l):
                valor = _dinheiro(l)
    if qtd == 1 and (venc or valor):
        c["parcelas"] = [{"identificacao": "1/1", "data": venc, "valor": valor}]
    elif qtd > 1:
        c["parcelas"] = _parcelas_mensais(qtd, c.get("vigencia_inicio"), valor)
    return c


# ---------------------------------------------------------------- SulAmérica

def _e_sulamerica(texto):
    t = texto.lower()
    return "sul américa" in t or "sulamérica" in t or "sul america" in t or "sulamerica" in t


def _parse_sulamerica(linhas, texto, alvo):
    c = {}

    if alvo == "cliente":
        i_dados = _idx(linhas, "DADOS DO SEGURADO")
        i_nome = _idx(linhas, "Nome:", inicio=i_dados)
        if i_nome >= 0:
            for l in linhas[i_nome + 1:i_nome + 8]:
                if _parece_nome(l):
                    c["nome"] = _titulo(l)
                    break
        cpf = _primeiro_cpf(texto) or _primeiro_cpf(texto, exigir_dv=False)
        if cpf:
            c["cpf"] = cpf
        end = _apos(linhas, "Endereço:", lambda l: " - " in l and len(l) > 15, inicio=i_dados)
        if end:
            c.update(_endereco_por_travessao(end))
        # nascimento + vigência: 3 datas em sequência após "Término da Vigência"
        i_vig = _idx(linhas, "Término da Vigência")
        datas = [l for l in linhas[i_vig + 1:i_vig + 12] if _e_data(l)] if i_vig >= 0 else []
        if datas:
            c["data_nascimento"] = _data_iso(datas[0])
        email = _RE_EMAIL.search(texto)
        if email and "susep" not in email.group(0).lower() and "yelum" not in email.group(0).lower():
            c["email"] = email.group(0).lower()
        return c

    # ---- apólice ----
    num = _apos(linhas, "NÚMERO DA APÓLICE", lambda l: re.fullmatch(r"\d[\d.\-/]*", l))
    if num:
        c["numero_apolice"] = num.strip()
    i_vig = _idx(linhas, "Término da Vigência")
    datas = [l for l in linhas[i_vig + 1:i_vig + 12] if _e_data(l)] if i_vig >= 0 else []
    if len(datas) >= 3:
        c["vigencia_inicio"] = _data_iso(datas[1])
        c["vigencia_fim"] = _data_iso(datas[2])
    elif len(datas) == 2:
        c["vigencia_inicio"], c["vigencia_fim"] = _data_iso(datas[0]), _data_iso(datas[1])

    i_pr = _idx(linhas, "Prêmio Líquido (por parcela)", "Prêmio Líquido")
    nums = []
    if i_pr >= 0:
        for l in linhas[i_pr + 1:i_pr + 12]:
            if _e_dinheiro(l) or _e_inteiro(l):
                nums.append(l)
            elif nums:
                break
    if nums:
        c["premio_liquido"] = _dinheiro(nums[0])
    # ordem típica: [prêmio líq, IOF, valor da parcela, qtd, prêmio total]
    i_qtd = next((k for k, x in enumerate(nums) if _e_inteiro(x)), len(nums))
    qtd = int(nums[i_qtd]) if i_qtd < len(nums) else None
    dinheiros_antes = [x for x in nums[:i_qtd] if _e_dinheiro(x)]
    valor_parc = dinheiros_antes[-1] if len(dinheiros_antes) > 1 else (dinheiros_antes[0] if dinheiros_antes else None)
    if qtd and qtd > 1:
        c["parcelas"] = _parcelas_mensais(qtd, c.get("vigencia_inicio"), _dinheiro(valor_parc))

    fp = _forma_pgto(texto)
    if fp:
        c["forma_pagamento"] = fp
    c["seguradora"] = "Sul América"
    mr = re.search(r"RAMO[:\s]+([A-ZÀ-Ú][A-ZÀ-Ú ]+)", texto)
    if mr:
        nome_ramo = mr.group(1).strip()
        c["tipo_seguro"] = "Vida" if "VIDA" in nome_ramo else _titulo(nome_ramo)
    return c


def _parcelas_mensais(qtd, inicio_iso, valor):
    parcelas = []
    y = m = d = None
    if inicio_iso:
        try:
            y, m, d = (int(x) for x in inicio_iso.split("-"))
        except ValueError:
            y = None
    for k in range(1, qtd + 1):
        data = None
        if y:
            mm = m + (k - 1)
            ano, mes = y + (mm - 1) // 12, (mm - 1) % 12 + 1
            dia = min(d, [31, 29 if ano % 4 == 0 and (ano % 100 or ano % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1])
            data = f"{ano:04d}-{mes:02d}-{dia:02d}"
        parcelas.append({"identificacao": f"{k}/{qtd}", "data": data, "valor": valor})
    return parcelas


# ---------------------------------------------------------------- genérico (reserva)

def _parse_generico(texto, alvo):
    from leitura_pdf_generico import extrair_campos_cliente, extrair_campos_apolice
    return extrair_campos_cliente(texto) if alvo == "cliente" else extrair_campos_apolice(texto)


# ---------------------------------------------------------------- fachada

def ler_pdf(pdf_bytes, alvo):
    """alvo in {'cliente', 'apolice'}. Devolve dict pronto pro JSON da rota."""
    texto, origem = extrair_texto(pdf_bytes)
    if origem == "vazio" or not texto:
        return {"ok": False, "origem": origem, "campos": {}, "texto": "",
                "aviso": "Não consegui ler texto desse PDF (nem por OCR)."}

    linhas = _linhas(texto)
    if _e_yelum(texto):
        seguradora, campos = "Yelum", _parse_yelum(linhas, texto, alvo)
    elif _e_sulamerica(texto):
        seguradora, campos = "SulAmérica", _parse_sulamerica(linhas, texto, alvo)
    else:
        seguradora, campos = None, _parse_generico(texto, alvo)

    campos = {k: v for k, v in campos.items() if v not in (None, "", [])}
    achados = sum(1 for k in campos if k != "parcelas") + (1 if campos.get("parcelas") else 0)

    if achados == 0:
        aviso = "Nada reconhecido — me manda esse PDF pra eu ajustar a leitura."
    elif origem == "ocr":
        aviso = "Lido por OCR — confira com atenção."
    elif seguradora:
        aviso = f"Layout reconhecido: {seguradora}. Confira antes de salvar."
    else:
        aviso = "Layout não reconhecido — leitura genérica, confira tudo."

    return {"ok": achados > 0, "origem": origem, "campos": campos,
            "seguradora_detectada": seguradora, "texto": texto[:8000], "aviso": aviso}
