"""Lê um PDF de apólice e tenta extrair os campos do cadastro (cliente e apólice).

Existem MUITOS layouts de apólice diferentes (cada seguradora, e o Quiver, gera de um jeito),
então aqui é tudo heurística e melhor-esforço: o que for encontrado volta preenchido, o resto
fica em branco pro usuário completar. Nada é salvo automaticamente.

Fluxo: extrai o texto com o PyMuPDF; se vier quase vazio (PDF digitalizado), rasteriza as
páginas e passa OCR (Tesseract, idioma português).
"""

import io
import os
import re

import pymupdf  # PyMuPDF

from validacao import cpf_valido, para_decimal, formatar_numero, so_digitos

# Tesseract: usa o do PATH; senão tenta o caminho padrão de instalação no Windows.
_TESSERACT_PADRAO = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

_MAX_PAGINAS_OCR = 6          # limita o OCR pra não travar em PDF gigante
_MIN_TEXTO_UTIL = 120         # abaixo disso, considera "sem texto" e parte pro OCR

# seguradoras mais comuns no mercado BR (só pra reconhecer no cabeçalho do PDF)
_SEGURADORAS = [
    "Porto Seguro", "Azul Seguros", "Itaú Seguros", "Bradesco Seguros", "SulAmérica",
    "Allianz", "Tokio Marine", "Liberty Seguros", "Mapfre", "HDI Seguros", "Zurich",
    "Sompo Seguros", "Yelum", "Suhai", "Aliro", "Pottencial", "Ezze Seguros",
    "Excelsior", "Mitsui Sumitomo", "Akad", "Chubb", "Berkley", "Icatu", "MetLife",
    "Prudential", "Sabemi", "Kovr", "Junto Seguros", "Essor",
]


# ---------------------------------------------------------------- extração de texto

def extrair_texto(pdf_bytes):
    """Devolve (texto, origem) com origem em {'texto', 'ocr', 'vazio'}."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return "", "vazio"

    with doc:
        partes = [pag.get_text("text") for pag in doc]
        texto = "\n".join(partes).strip()
        if len(texto) >= _MIN_TEXTO_UTIL:
            return texto, "texto"

        # pouco ou nenhum texto -> tenta OCR
        ocr = _ocr_documento(doc)
        if len(ocr.strip()) >= len(texto):
            return ocr.strip(), "ocr"
        return texto, ("texto" if texto else "vazio")


def _ocr_documento(doc):
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return ""

    exe = _TESSERACT_PADRAO if os.path.exists(_TESSERACT_PADRAO) else None
    if exe:
        pytesseract.pytesseract.tesseract_cmd = exe

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
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            saidas.append(pytesseract.image_to_string(img, lang=linguas))
        except Exception:
            continue
    return "\n".join(saidas)


# ---------------------------------------------------------------- utilidades

def _norm(texto):
    # junta espaços, mas preserva quebras de linha (várias heurísticas usam a linha)
    linhas = [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in (texto or "").splitlines()]
    return "\n".join(l for l in linhas if l)


# separador rótulo->valor que NÃO cruza quebra de linha; tolera ":", "-" e a
# "linha pontilhada" de certificados ("Contratante ...... FULANO")
_S = r"[ \t]*[.:_\-]*[ \t]*"
_DATA = r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"


def _achar(texto, padrao, grupo=1, flags=re.I):
    m = re.search(padrao, texto, flags)
    return m.group(grupo).strip() if m else None


def _data_iso(bruto):
    if not bruto:
        return None
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", bruto)
    if not m:
        return None
    d, mes, a = m.groups()
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


def _limpar_nome(bruto):
    if not bruto:
        return None
    # corta no primeiro rótulo que costuma vir depois do nome
    nome = re.split(r"\b(cpf|cnpj|rg|data|nascimento|end|endere[çc]o|ap[óo]lice|sexo|e-?mail)\b",
                    bruto, flags=re.I)[0]
    # tira prefixos de rótulo grudados no começo ("Nome do Segurado ...")
    nome = re.sub(r"^(?:(?:nome|do|da|de|segurad[oa]|contratante|proponente|client[e])\b[ .:-]*)+",
                  "", nome, flags=re.I)
    nome = re.sub(r"[^A-Za-zÀ-ÿ'.\s]", " ", nome)
    nome = re.sub(r"\s{2,}", " ", nome).strip(" .-")
    if len(nome) < 5 or " " not in nome:
        return None
    if nome.isupper() or nome.islower():
        nome = nome.title()
    return nome


# ---------------------------------------------------------------- cliente

def extrair_campos_cliente(texto):
    t = _norm(texto)
    campos = {}

    # CPF: primeiro que passa no dígito verificador
    for m in re.finditer(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b", t):
        if cpf_valido(m.group(1)):
            campos["cpf"] = so_digitos(m.group(1))
            break

    nome = (_achar(t, r"nome[ \t]+(?:d[oae][ \t]+)?(?:segurad[oa]|client[e]|contratante|proponente)" + _S + r"(.+)")
            or _achar(t, r"\bsegurad[oa]\b" + _S + r"(.+)")
            or _achar(t, r"\bcontratante\b" + _S + r"(.+)")
            or _achar(t, r"\bproponente\b" + _S + r"(.+)")
            or _achar(t, r"^nome[ \t]*[:\-][ \t]*(.+)", flags=re.I | re.M))
    nome = _limpar_nome(nome)
    if nome:
        campos["nome"] = nome

    nasc = _achar(t, r"(?:nascimento|nasc\.?|dt[ .]*nasc)" + _S + r"(" + _DATA + r")")
    if _data_iso(nasc):
        campos["data_nascimento"] = _data_iso(nasc)

    sexo = _achar(t, r"sexo" + _S + r"(masculino|feminino|m|f)\b")
    if sexo:
        campos["sexo"] = {"m": "Masculino", "f": "Feminino"}.get(sexo.lower(), sexo.title())

    email = _achar(t, r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
    if email:
        campos["email"] = email.lower()

    tel = _achar(t, r"(?:telefone|tel\.?|fone|celular|whats)" + _S + r"(\(?\d{2,3}\)?[ .\-]?\d{4,5}[ .\-]?\d{4})")
    if tel:
        m = re.search(r"\(?(\d{2,3})\)?[ .\-]?(\d{4,5})[ .\-]?(\d{4})", tel)
        if m:
            ddd = m.group(1)
            campos["tel_ddd"] = ddd[1:] if len(ddd) == 3 and ddd[0] == "0" else ddd[:2]
            campos["tel_numero"] = m.group(2) + m.group(3)

    # CEP: prefere o que vem logo depois da palavra CEP
    cep = _achar(t, r"cep" + _S + r"(\d{5}-?\d{3})") or _achar(t, r"\b(\d{5}-?\d{3})\b")
    if cep:
        campos["end_cep"] = so_digitos(cep)

    logr = _achar(t, r"(?:endere[çc]o|logradouro|\bend\.|avenida|\brua\b|\bav\.)" + _S + r"(.+)")
    if logr:
        logr = re.split(r"\b(n[ºo°]|n[úu]mero|bairro|cep|compl)", logr, flags=re.I)[0]
        logr = logr.strip(" ,.-")
        if len(logr) > 3:
            campos["end_rua"] = logr[:120]

    # número da casa: ignora "Apólice Nº 0531.12..." (número seguido de . ou / e mais dígito)
    num = _achar(t, r"(?<!ap[óo]lice )(?:n[ºo°]|n[úu]mero)\.?" + _S + r"(\d{1,5})(?![\d./])")
    if num:
        campos["end_numero"] = num

    bairro = _achar(t, r"bairro" + _S + r"(.+)")
    if bairro:
        bairro = re.split(r"\b(cidade|munic|cep|uf|estado)\b", bairro, flags=re.I)[0].strip(" ,.-")
        if bairro:
            campos["end_bairro"] = bairro[:80]

    cidade = _achar(t, r"(?:cidade|munic[íi]pio)" + _S + r"([A-Za-zÀ-ÿ' .]+?)[ \t]*[-/][ \t]*([A-Z]{2})\b", grupo=1)
    uf = _achar(t, r"(?:cidade|munic[íi]pio)" + _S + r"[A-Za-zÀ-ÿ' .]+?[ \t]*[-/][ \t]*([A-Z]{2})\b")
    if not uf:
        uf = _achar(t, r"\b(?:uf|estado)" + _S + r"([A-Z]{2})\b")
    if not cidade:
        # linha solta "Cidade-UF" ou "Cidade / UF" (com UF válida), típica logo antes/depois do CEP
        for mc in re.finditer(r"(?m)^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' .]{2,40})[ \t]*[-/][ \t]*([A-Z]{2})\b", t):
            if mc.group(2).upper() in _UFS:
                cidade, uf = mc.group(1), mc.group(2)
                break
    if cidade:
        campos["end_cidade"] = cidade.strip().title()
    if uf and uf.upper() in _UFS:
        campos["end_estado"] = uf.upper()

    return campos


# ---------------------------------------------------------------- apólice

def extrair_campos_apolice(texto):
    t = _norm(texto)
    campos = {}

    seg = _achar(t, r"(?:seguradora|companhia\s+seguradora|cia\.?\s*seguradora|companhia)" + _S + r"([A-Za-zÀ-ÿ0-9&/.\- ]{3,50})")
    if seg:
        seg = re.split(r"\b(cnpj|ap[óo]lice|susep|processo|ramo)\b", seg, flags=re.I)[0].strip(" .-")
    if not seg:
        cabecalho = "\n".join(t.splitlines()[:12])
        for nome in _SEGURADORAS:
            if re.search(r"\b" + re.escape(nome.split()[0]) + r"\b", cabecalho, re.I):
                seg = nome
                break
    if seg and len(seg) >= 3:
        campos["seguradora"] = seg[:60]

    numero = (_achar(t, r"(?:n[ºo°]?[ \t]*d[ao][ \t]*)?ap[óo]lice[ \t]*(?:n[ºo°]?\.?)?" + _S + r"([0-9][0-9A-Za-z.\-/]{4,})")
              or _achar(t, r"proposta[ \t]*(?:n[ºo°]?\.?)?" + _S + r"([0-9][0-9A-Za-z.\-/]{4,})")
              or _achar(t, r"ap[óo]lice[^\n]{0,20}?\b([0-9]{6,})\b"))
    if numero:
        campos["numero_apolice"] = numero.strip(" .-")

    # vigência: primeiro tenta rótulos "início/fim"; senão as duas primeiras datas
    # numa janela logo após a palavra "vigência".
    ini = _achar(t, r"in[íi]cio(?:[ \t]*de[ \t]*vig[êe]ncia)?" + _S + r"(" + _DATA + r")")
    fim = _achar(t, r"(?:fim|t[ée]rmino)(?:[ \t]*de[ \t]*vig[êe]ncia)?" + _S + r"(" + _DATA + r")")
    janela = _achar(t, r"vig[êe]ncia(.{0,160})", grupo=1, flags=re.I | re.S) or ""
    dv = re.findall(_DATA, janela)
    vi = _data_iso(ini) or (_data_iso(dv[0]) if dv else None)
    vf = _data_iso(fim) or (_data_iso(dv[1]) if len(dv) > 1 else None)
    if vi:
        campos["vigencia_inicio"] = vi
    if vf:
        campos["vigencia_fim"] = vf

    premio = (_achar(t, r"pr[êe]mio\s*l[íi]quido\s*[:\-]?\s*R?\$?\s*([\d.]+,\d{2})")
              or _achar(t, r"pr[êe]mio\s*(?:total|bruto)?\s*[:\-]?\s*R?\$?\s*([\d.]+,\d{2})"))
    if _dinheiro(premio):
        campos["premio_liquido"] = _dinheiro(premio)

    pct = (_achar(t, r"comiss[ãa]o[^\n%]{0,20}?(\d{1,3}(?:[.,]\d{1,2})?)[ \t]*%")
           or _achar(t, r"comiss[ãa]o[ \t]*\(%\)" + _S + r"(\d{1,3}(?:[.,]\d{1,2})?)")
           or _achar(t, r"%[ \t]*(?:de[ \t]*)?comiss[ãa]o" + _S + r"(\d{1,3}(?:[.,]\d{1,2})?)"))
    if pct:
        campos["comissao_percentual"] = pct.replace(".", ",")
    cval = _achar(t, r"comiss[ãa]o[^\n]{0,20}?R\$?\s*([\d.]+,\d{2})")
    if _dinheiro(cval):
        campos["comissao_valor"] = _dinheiro(cval)

    campos["parcelas"] = _normalizar_ids_parcelas(_extrair_parcelas(t))
    return campos


def _extrair_parcelas(t):
    parcelas = []

    # 1) linhas tipo "1/12  10/03/2026  R$ 250,00"
    for m in re.finditer(
        r"(?m)^\s*(\d{1,2})\s*[/xª\-]\s*(\d{1,2})\b[^\n]*?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})[^\n]*?([\d.]+,\d{2})",
        t,
    ):
        i, total, data, valor = m.groups()
        parcelas.append({
            "identificacao": f"{int(i)}/{int(total)}",
            "data": _data_iso(data),
            "valor": _dinheiro(valor),
        })
    if parcelas:
        return parcelas

    # 2) linhas com a palavra "parcela" + data + valor
    for m in re.finditer(
        r"(?i)parcela\s*(\d{1,2})?[^\n]*?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})[^\n]*?([\d.]+,\d{2})", t
    ):
        i, data, valor = m.groups()
        parcelas.append({
            "identificacao": (f"{int(i)}" if i else None),
            "data": _data_iso(data),
            "valor": _dinheiro(valor),
        })
    if parcelas:
        return parcelas

    # 3) "12x de R$ 250,00" -> gera as identificações, sem datas
    m = re.search(r"\b(\d{1,2})\s*x\s*(?:de\s*)?R?\$?\s*([\d.]+,\d{2})", t, re.I)
    if m:
        n, valor = int(m.group(1)), _dinheiro(m.group(2))
        parcelas = [{"identificacao": f"{k}/{n}", "data": None, "valor": valor} for k in range(1, n + 1)]
    return parcelas


def _normalizar_ids_parcelas(parcelas):
    """Se as identificações forem 1,2,3,... sequenciais, vira "1/N", "2/N"..."""
    ids = [p.get("identificacao") for p in parcelas]
    if parcelas and all(i and i.isdigit() for i in ids):
        seq = [int(i) for i in ids]
        if seq == list(range(1, len(seq) + 1)):
            n = len(seq)
            for k, p in enumerate(parcelas, start=1):
                p["identificacao"] = f"{k}/{n}"
    return parcelas


# ---------------------------------------------------------------- fachada

def ler_pdf(pdf_bytes, alvo):
    """alvo in {'cliente', 'apolice'}. Devolve dict pronto pro JSON da rota."""
    texto, origem = extrair_texto(pdf_bytes)
    if origem == "vazio" or not texto:
        return {"ok": False, "origem": origem, "campos": {},
                "aviso": "Não consegui ler texto desse PDF (nem por OCR)."}

    if alvo == "cliente":
        campos = extrair_campos_cliente(texto)
    else:
        campos = extrair_campos_apolice(texto)

    achados = sum(1 for k, v in campos.items() if v and k != "parcelas")
    achados += 1 if campos.get("parcelas") else 0
    return {
        "ok": achados > 0,
        "origem": origem,
        "campos": campos,
        "aviso": ("Nada reconhecido — o layout dessa apólice deve ser diferente."
                  if achados == 0 else
                  ("Lido por OCR — confira com atenção." if origem == "ocr" else "")),
    }
