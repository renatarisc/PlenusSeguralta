"""Lê PDFs de comparativos/cotações de seguradoras e tenta extrair os campos que
alimentam o formulário "Cotação → Gerar" (uma ou mais ofertas por PDF).

Diferente da leitura de apólice (leitura_pdf.py), os "campos" aqui são os que a
usuária cadastrou em Cotação → Campos — nome livre, tipo variável, id que muda
de instalação pra instalação. Por isso esse módulo devolve os valores extraídos
com CHAVES CANÔNICAS (ver `CHAVES`); quem chama (app.py) casa cada chave com o
campo real pelo nome/papel cadastrado.

Hoje só reconhece um layout — o do comparador de cotações que gera o primeiro
PDF de exemplo (várias ofertas lado a lado, cada uma com duas franquias,
"Reduzida 50%" e "Reduzida 25%"; sempre usamos a de 50%). A ideia é ir
agregando parsers por layout conforme surgirem PDFs de outras fontes, do mesmo
jeito que leitura_pdf.py faz por seguradora. Layout não reconhecido -> devolve
sem ofertas, nunca inventa dado.
"""

import re

from leitura_pdf import extrair_texto
from validacao import para_decimal, formatar_numero

# chaves que este módulo pode devolver em `oferta["campos"]`
CHAVES = (
    "danos_materiais", "danos_corporais", "app_morte", "danos_morais",
    "assistencia", "vidros", "carro_reserva", "pequenos_reparos",
    "protecao_roda", "tipo_oficina", "valor_franquia", "valor_seguro",
    "num_parcelas",
)

_MOEDA = re.compile(r"^R?\$?\s*(\d{1,3}(?:\.\d{3})*,\d{2})$")
_PARCELAS_N = re.compile(r"^(\d+)\s+Parcelas?$", re.I)


def _linhas(texto):
    return [re.sub(r"[ \t ]+", " ", l).strip() for l in (texto or "").splitlines() if l.strip()]


def _idx(linhas, alvo, inicio=0, fim=None):
    """1º índice (>= inicio, < fim) cuja linha é EXATAMENTE `alvo` (sem acentuar case)."""
    alvo_baixo = alvo.lower()
    fim = len(linhas) if fim is None else fim
    for i in range(max(inicio, 0), min(fim, len(linhas))):
        if linhas[i].lower() == alvo_baixo:
            return i
    return -1


def _todos_idx(linhas, alvo):
    alvo_baixo = alvo.lower()
    return [i for i, l in enumerate(linhas) if l.lower() == alvo_baixo]


def _e_dinheiro(l):
    return bool(_MOEDA.match(l or ""))


def _dinheiro(l):
    m = _MOEDA.match(l or "")
    if not m:
        return None
    v = para_decimal(m.group(1))
    return formatar_numero(v) if v is not None else None


def _primeiro_dinheiro_apos(linhas, inicio, limite=6):
    for l in linhas[inicio:inicio + limite]:
        if _e_dinheiro(l):
            return _dinheiro(l)
    return None


def _apos_prefixo(linhas, prefixo, inicio, fim):
    """Valor (linha seguinte) do 1º rótulo em linhas[inicio:fim] que começa com `prefixo`."""
    baixo = prefixo.lower()
    for i in range(inicio, max(inicio, fim - 1)):
        if linhas[i].lower().startswith(baixo):
            return linhas[i + 1]
    return None


def _sim_nao(bruto):
    """'Indisponível'/'Não contratada' -> 'Não'; 'Disponível'/'Sim' -> 'Sim'; senão None."""
    v = (bruto or "").strip().lower()
    if not v:
        return None
    if "indispon" in v or v.startswith("não") or v.startswith("nao"):
        return "Não"
    if "disponí" in v or "disponi" in v or v in ("sim", "contratada", "contratado"):
        return "Sim"
    return None


def _titulo_pessoa(bruto):
    if not bruto:
        return None
    return " ".join(p.capitalize() for p in bruto.strip().split())


# ---------------------------------------------------------------- layout "comparador"

def _extrair_cliente(linhas):
    i = _idx(linhas, "Nome do segurado")
    if i < 0 or i + 1 >= len(linhas):
        return None
    return _titulo_pessoa(linhas[i + 1])


def _extrair_titulo_oferta(linhas, ini, fim_cobertura):
    """Texto entre a linha "COBERTURAS BÁSICAS" (ini) e o início do bloco de cobertura
    (fim_cobertura) -- é o nome do plano/produto, às vezes quebrado em 2 linhas."""
    partes = linhas[ini + 1:fim_cobertura]
    return " ".join(partes).strip() or None


def _extrair_campos_cobertura(linhas, ini, fim):
    c = {}

    v = _apos_prefixo(linhas, "Danos Materiais a terceiros", ini, fim)
    if v and _e_dinheiro(v):
        c["danos_materiais"] = _dinheiro(v)

    v = _apos_prefixo(linhas, "Danos Corporais a terceiros", ini, fim)
    if v and _e_dinheiro(v):
        c["danos_corporais"] = _dinheiro(v)

    v = _apos_prefixo(linhas, "APP Morte", ini, fim)
    if v and _e_dinheiro(v):
        c["app_morte"] = _dinheiro(v)

    v = _apos_prefixo(linhas, "Danos Morais", ini, fim)
    if v and _e_dinheiro(v):
        c["danos_morais"] = _dinheiro(v)

    v = _apos_prefixo(linhas, "Assistência", ini, fim)
    if v:
        # "250 KM" -> só "250" (o rótulo do campo já mostra a unidade "Km" ao lado);
        # "Guincho ilimitado" -> "Ilimitada"; outro texto qualquer entra como veio.
        m = re.match(r"^(\d+)\s*km$", v, re.I)
        if m:
            c["assistencia"] = m.group(1)
        elif "ilimitad" in v.lower():
            c["assistencia"] = "Ilimitada"
        else:
            c["assistencia"] = v

    v = _apos_prefixo(linhas, "Vidros", ini, fim)
    if v:
        c["vidros"] = v

    v = _apos_prefixo(linhas, "Carro Reserva", ini, fim)
    if v:
        # "Não contratada" -> deixa em branco (o campo é numérico/dias; sem info melhor
        # do que inventar um "0"). Só grava se vier alguma coisa que pareça número.
        m = re.match(r"(\d+)", v)
        if m:
            c["carro_reserva"] = m.group(1)

    v = _apos_prefixo(linhas, "Pequenos Reparos", ini, fim)
    sn = _sim_nao(v)
    if sn:
        c["pequenos_reparos"] = sn

    v = _apos_prefixo(linhas, "Proteção de rodas e pneus", ini, fim) \
        or _apos_prefixo(linhas, "Proteção de Rodas", ini, fim)
    sn = _sim_nao(v)
    if sn:
        c["protecao_roda"] = sn

    return c


def _extrair_franquias_e_valor_seguro(linhas, campos_por_oferta):
    """Preenche `valor_franquia`, `valor_seguro` e `num_parcelas` em cada dict de
    `campos_por_oferta` (na ordem das ofertas), sempre pegando a 1ª franquia listada
    (== "Reduzida 50%", a que a usuária pediu pra sempre usar)."""
    n = len(campos_por_oferta)
    if n == 0:
        return

    idx_franquias = _idx(linhas, "FRANQUIAS DO VEICULO")
    if idx_franquias >= 0:
        idxs_valores = [i for i, l in enumerate(linhas)
                        if i > idx_franquias and l.lower() == "valores"]
        for k, campos in enumerate(campos_por_oferta):
            if k >= len(idxs_valores):
                break
            v = _primeiro_dinheiro_apos(linhas, idxs_valores[k] + 1, limite=2)
            if v:
                campos["valor_franquia"] = v

    idxs_tabela = _todos_idx(linhas, "PARCELAS (* SEM JUROS)")
    for k, campos in enumerate(campos_por_oferta):
        if k >= len(idxs_tabela):
            break
        ini = idxs_tabela[k]
        fim = idxs_tabela[k + 1] if k + 1 < len(idxs_tabela) else len(linhas)
        i_vista = _idx(linhas, "À Vista", inicio=ini, fim=fim)
        if i_vista >= 0:
            v = _primeiro_dinheiro_apos(linhas, i_vista + 1, limite=6)
            if v:
                campos["valor_seguro"] = v
        maior = 0
        for l in linhas[ini:fim]:
            m = _PARCELAS_N.match(l)
            if m:
                maior = max(maior, int(m.group(1)))
        if maior:
            campos["num_parcelas"] = str(maior)


def _extrair_tipo_oficina(texto, campos_por_oferta):
    referenciada = "referenciada" in (texto or "").lower()
    valor = "Referenciada" if referenciada else "Livre escolha"
    for campos in campos_por_oferta:
        campos["tipo_oficina"] = valor


def _layout_comparador(linhas, texto):
    idxs_cob = _todos_idx(linhas, "COBERTURAS BÁSICAS")
    if not idxs_cob:
        return None
    n = len(idxs_cob)

    idx_franquias = _idx(linhas, "FRANQUIAS DO VEICULO")
    limite_final = idx_franquias if idx_franquias >= 0 else len(linhas)

    # os N cabeçalhos "COBERTURAS BÁSICAS" + título vêm todos juntos primeiro; só depois
    # começam os N blocos de dados de cobertura (cada um com seu próprio "Tipo de
    # cobertura"). Then usa só as ocorrências dentro da janela de dados.
    idxs_tipo_cob = [i for i in _todos_idx(linhas, "Tipo de cobertura")
                     if idxs_cob[-1] < i < limite_final]

    inicio_dados = idxs_tipo_cob[0] if idxs_tipo_cob else limite_final

    ofertas = []
    for k, ini in enumerate(idxs_cob):
        fim_titulo = idxs_cob[k + 1] if k + 1 < n else inicio_dados
        titulo = _extrair_titulo_oferta(linhas, ini, fim_titulo)

        if k < len(idxs_tipo_cob):
            ini_cobertura = idxs_tipo_cob[k]
            fim_cobertura = idxs_tipo_cob[k + 1] if k + 1 < len(idxs_tipo_cob) else limite_final
            campos = _extrair_campos_cobertura(linhas, ini_cobertura, fim_cobertura)
        else:
            campos = {}
        ofertas.append({"seguradora": titulo, "campos": campos})

    campos_por_oferta = [o["campos"] for o in ofertas]
    _extrair_franquias_e_valor_seguro(linhas, campos_por_oferta)
    _extrair_tipo_oficina(texto, campos_por_oferta)

    return {"cliente": _extrair_cliente(linhas), "ofertas": ofertas}


# ---------------------------------------------------------------- fachada

def ler_pdf_cotacao(pdf_bytes):
    """Devolve dict pronto pro JSON da rota (ver `app.py: cotacao_ler_pdf`)."""
    texto, origem = extrair_texto(pdf_bytes)
    if origem == "vazio" or not texto:
        return {"ok": False, "origem": origem, "cliente": None, "ofertas": [],
                "texto": "", "aviso": "Não consegui ler texto desse PDF (nem por OCR)."}

    linhas = _linhas(texto)
    resultado = _layout_comparador(linhas, texto)

    if not resultado or not resultado["ofertas"]:
        return {"ok": False, "origem": origem, "cliente": None, "ofertas": [],
                "texto": texto[:8000],
                "aviso": "Layout não reconhecido — me manda esse PDF pra eu ajustar a leitura."}

    n_campos = sum(len(o["campos"]) for o in resultado["ofertas"])
    if origem == "ocr":
        aviso = "Lido por OCR — confira com atenção."
    else:
        aviso = f"{len(resultado['ofertas'])} oferta(s) reconhecida(s). Confira antes de gerar."

    return {"ok": n_campos > 0, "origem": origem, "cliente": resultado["cliente"],
            "ofertas": resultado["ofertas"], "texto": texto[:8000], "aviso": aviso}
