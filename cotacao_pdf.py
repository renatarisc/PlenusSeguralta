"""PDF do comparativo de cotações (ReportLab).

`gerar(cliente, cotacoes, campos)` devolve os bytes do PDF: uma tabela única em que a
1ª coluna são os nomes dos campos cadastrados e cada coluna seguinte é uma cotação
(uma seguradora). Cabeçalho/rodapé no mesmo padrão do relatório de fluxo de caixa.

- `cliente`  : str
- `cotacoes` : lista de {"seguradora": str, "valores": {campo_id: "texto"}}
- `campos`   : lista de {"id", "nome", "tipo"} na ordem desejada
"""

import io
import os
import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Table, TableStyle)

from relatorio_pdf import (LARANJA, GRAFITE, CINZA_TXT, CINZA_LINHA, CINZA_CAB1,
                           MARGEM, _logo, _NumCanvas)
from validacao import formatar_moeda, para_decimal, formatar_data_br

_cel = ParagraphStyle("cc_cel", fontName="Helvetica", fontSize=8, leading=10)
_cel_c = ParagraphStyle("cc_celC", parent=_cel, alignment=TA_CENTER)
_campo = ParagraphStyle("cc_campo", parent=_cel, fontName="Helvetica-Bold")
_th = ParagraphStyle("cc_th", parent=_cel, fontName="Helvetica-Bold", fontSize=8,
                     textColor=colors.white, alignment=TA_CENTER)
_vazio = ParagraphStyle("cc_vazio", parent=_cel, fontSize=9, textColor=CINZA_TXT,
                        alignment=TA_CENTER, spaceBefore=24)
_cel_c_forte = ParagraphStyle("cc_celCforte", parent=_cel_c, fontName="Helvetica-Bold")


def _p(txt, st):
    return Paragraph(escape(str(txt)), st)


_RE_UNIDADE = re.compile(r"\s*\(([^()]+)\)\s*$")


def _unidade(nome):
    """Sufixo entre parênteses no fim do nome do campo -> unidade. Ex.: 'Assistência (Km)' -> 'km'."""
    m = _RE_UNIDADE.search(nome or "")
    return m.group(1).strip().lower() if m else ""


def _rotulo(nome):
    """Nome do campo sem o sufixo entre parênteses. Ex.: 'Carro Reserva (dias)' -> 'Carro Reserva'."""
    return _RE_UNIDADE.sub("", (nome or "").strip())


# o parcelamento é calculado na linha do campo marcado (no cadastro) com papel
# "num_parcelas": ele mostra "Nx de R$ y" dividindo o valor do campo com papel
# "base_parcelamento". Sem esses papéis definidos, nada muda no PDF.


def _fmt_parcelamento(qtd, valor_base):
    """'12' + 3600 -> '12x de R$ 300,00'. Sem base ou qtd inválida -> texto como veio."""
    q = (qtd or "").strip()
    if not q:
        return "—"
    try:
        n = int(float(q.replace(".", "").replace(",", ".")))
    except ValueError:
        return q
    base = para_decimal(valor_base)
    if n > 0 and base:
        return f"{n}x de {formatar_moeda(round(base / n, 2))}"
    return q


def _fmt(valor, tipo, unidade=""):
    v = (valor or "").strip()
    if not v:
        return "—"
    if tipo == "valor":
        m = formatar_moeda(v)
        return v if m == "—" else m   # texto livre (ex.: "sob consulta") passa como veio
    if tipo == "data":
        return formatar_data_br(v)
    if tipo == "percentual":
        return v if v.endswith("%") else f"{v}%"
    if tipo == "numerico" and unidade:
        return f"{v} {unidade}"
    return v


_BANNER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "static", "img", "seguro-e-seguralta.png")


def _banner_seguralta(cnv, w, topo):
    """Banner 'SEGURO É SEGURALTA' centralizado na faixa do cabeçalho. Nunca aborta o PDF."""
    try:
        img = ImageReader(_BANNER)
        iw, ih = img.getSize()
        alt = 30
        larg = alt * iw / ih
        cnv.drawImage(img, (w - larg) / 2, topo - alt, width=larg, height=alt,
                     mask='auto')
    except Exception:
        pass


def _cabecalho(cnv, doc, ctx):
    w, _h = doc.pagesize
    topo = doc.pagesize[1] - MARGEM
    _logo(cnv, MARGEM, topo, 27)
    tx = MARGEM + 27 + 10
    cnv.setFillColor(GRAFITE)
    cnv.setFont("Helvetica-Bold", 13)
    cnv.drawString(tx, topo - 11, "Plenus")
    cnv.setFont("Helvetica", 8)
    cnv.setFillColor(CINZA_TXT)
    cnv.drawString(tx, topo - 23, "Comparativo de cotações")
    _banner_seguralta(cnv, w, topo)
    cnv.setFont("Helvetica", 7.5)
    cnv.drawRightString(w - MARGEM, topo - 6, "Emitido em " + ctx["emissao"])
    if ctx.get("cliente"):
        cnv.setFont("Helvetica-Bold", 8)
        cnv.setFillColor(GRAFITE)
        cnv.drawRightString(w - MARGEM, topo - 18, "Cliente: " + ctx["cliente"])
    cnv.setStrokeColor(GRAFITE)
    cnv.setLineWidth(1.3)
    cnv.line(MARGEM, topo - 34, w - MARGEM, topo - 34)


def gerar(cliente, cotacoes, campos):
    cliente = (cliente or "").strip()
    cotacoes = list(cotacoes or [])
    campos = list(campos or [])

    muitas = len(cotacoes) >= 4
    pagesize = landscape(A4) if muitas else A4
    largura_util = pagesize[0] - 2 * MARGEM

    ctx = {"emissao": datetime.now().strftime("%d/%m/%Y às %H:%M"), "cliente": cliente}

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=pagesize, leftMargin=MARGEM, rightMargin=MARGEM,
        topMargin=MARGEM + 46, bottomMargin=MARGEM + 6,
        title="Comparativo de cotações", author="Plenus")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="corpo")
    doc.addPageTemplates([PageTemplate(
        id="pt", frames=[frame], onPage=lambda cnv, d: _cabecalho(cnv, d, ctx))])

    story = []
    if not cotacoes or not campos:
        story.append(_p("Nada para comparar — informe ao menos uma seguradora e cadastre campos.", _vazio))
    else:
        col_campo = min(180, max(120, largura_util * 0.32))
        col_val = (largura_util - col_campo) / len(cotacoes)
        col_widths = [col_campo] + [col_val] * len(cotacoes)

        cab = [_p("Serviço", _th)] + [
            _p(co.get("seguradora") or f"Cotação {i + 1}", _th) for i, co in enumerate(cotacoes)
        ]
        base_cid = next((c["id"] for c in campos if c.get("papel") == "base_parcelamento"), None)
        parc_cid = next((c["id"] for c in campos if c.get("papel") == "num_parcelas"), None)

        linhas = [cab]
        for c in campos:
            uni = _unidade(c["nome"]) if c["tipo"] == "numerico" else ""
            linha = [_p(_rotulo(c["nome"]), _campo)]
            for co in cotacoes:
                vals = co.get("valores") or {}
                if c["id"] == parc_cid:
                    txt = _fmt_parcelamento(vals.get(c["id"]), vals.get(base_cid))
                    linha.append(_p(txt, _cel_c_forte))
                else:
                    linha.append(_p(_fmt(vals.get(c["id"]), c["tipo"], uni), _cel_c))
            linhas.append(linha)

        t = Table(linhas, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), GRAFITE),
            ("GRID", (0, 0), (-1, -1), 0.6, CINZA_LINHA),
            ("LINEBELOW", (0, 0), (-1, 0), 1.1, GRAFITE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfc")]),
        ]))
        story.append(t)

    rodape = "Plenus · " + ctx["emissao"]
    doc.build(story, canvasmaker=lambda *a, **k: _NumCanvas(*a, rodape=rodape, **k))
    return buf.getvalue()
