"""Gera o PDF do relatório de fluxo de caixa (ReportLab).

`gerar(ctx)` recebe o dicionário de contexto montado por `app._relatorio_contexto`
e devolve os bytes do PDF. Cabeçalho próprio (logo SEGURALTA + data/hora de emissão
+ título) desenhado em toda página; rodapé com "página X de Y".
"""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as _canvas
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from validacao import formatar_data_br, formatar_moeda, formatar_numero

# ---------- paleta ----------
LARANJA = colors.HexColor("#e8641e")
GRAFITE = colors.HexColor("#2b2b2b")
CINZA_TXT = colors.HexColor("#5b6068")
CINZA_LINHA = colors.HexColor("#dfe2e6")
CINZA_CAB1 = colors.HexColor("#eceff3")
CINZA_CAB2 = colors.HexColor("#f4f6f8")
CINZA_SUB = colors.HexColor("#f7f8fa")

MARGEM = 34
COLS = ["Descrição", "Parc.", "Vencimento", "Pagamento", "Valor", "Situação"]
COL_W = [214, 40, 74, 74, 72, 53]   # soma = 527 (A4 - 2*34)

# ---------- estilos de célula ----------
_cel = ParagraphStyle("cel", fontName="Helvetica", fontSize=7.6, leading=9.4)
_cel_c = ParagraphStyle("celC", parent=_cel, alignment=TA_CENTER)
_cel_r = ParagraphStyle("celR", parent=_cel, alignment=TA_RIGHT)
_desc = ParagraphStyle("desc", parent=_cel, fontName="Helvetica-Bold")
_th = ParagraphStyle("th", parent=_cel, fontName="Helvetica-Bold", fontSize=7,
                     textColor=CINZA_TXT)
_th_c = ParagraphStyle("thC", parent=_th, alignment=TA_CENTER)
_th_r = ParagraphStyle("thR", parent=_th, alignment=TA_RIGHT)
_grp1 = ParagraphStyle("grp1", parent=_cel, fontName="Helvetica-Bold", fontSize=8.4)
_grp2 = ParagraphStyle("grp2", parent=_cel, fontName="Helvetica-Bold", fontSize=7.8)
_sub = ParagraphStyle("sub", parent=_cel, fontSize=7.2, textColor=CINZA_TXT)
_sub_b = ParagraphStyle("subB", parent=_sub, fontName="Helvetica-Bold", textColor=GRAFITE)
_sub_r = ParagraphStyle("subR", parent=_sub_b, alignment=TA_RIGHT)
_tot = ParagraphStyle("tot", parent=_cel, fontName="Helvetica-Bold", fontSize=8.6)
_tot_r = ParagraphStyle("totR", parent=_tot, alignment=TA_RIGHT)
_vazio = ParagraphStyle("vazio", parent=_cel, fontSize=9, textColor=CINZA_TXT,
                        alignment=TA_CENTER, spaceBefore=24)


def _d(iso):
    return formatar_data_br(iso) if iso else "—"


def _m(v):
    return formatar_moeda(v or 0)


def _sit(s):
    return {"pago": "Paga", "vencido": "Vencida"}.get(s.get("status"), "A pagar")


def _p(txt, st):
    return Paragraph(escape(str(txt)), st)


# ---------- cabeçalho / rodapé desenhados na página ----------
def _logo(cnv, x, ytop, alt):
    """Desenha a marca (montanha grafite + pico laranja) num quadrado `alt` pt."""
    sc = alt / 32.0
    def P(px, py):
        return (x + px * sc, ytop - py * sc)
    cnv.setFillColor(GRAFITE)
    p = cnv.beginPath()
    p.moveTo(*P(14, 4)); p.lineTo(*P(30, 30)); p.lineTo(*P(2, 30)); p.close()
    cnv.drawPath(p, fill=1, stroke=0)
    cnv.setFillColor(LARANJA)
    p = cnv.beginPath()
    p.moveTo(*P(22.5, 15)); p.lineTo(*P(30, 30)); p.lineTo(*P(15, 30)); p.close()
    cnv.drawPath(p, fill=1, stroke=0)


def _cabecalho(cnv, doc, ctx):
    w, h = A4
    topo = h - MARGEM
    _logo(cnv, MARGEM, topo, 27)
    tx = MARGEM + 27 + 10
    cnv.setFillColor(GRAFITE)
    cnv.setFont("Helvetica-Bold", 13)
    cnv.drawString(tx, topo - 11, "Plenus")
    cnv.setFont("Helvetica", 8)
    cnv.setFillColor(CINZA_TXT)
    sub = "Fluxo de caixa · Relatório de " + ("saídas" if ctx["tipo"] == "saidas" else "entradas")
    cnv.drawString(tx, topo - 23, sub)

    if ctx.get("data_ini") or ctx.get("data_fim"):
        periodo = "Período: %s a %s" % (_d(ctx.get("data_ini")) if ctx.get("data_ini") else "…",
                                             _d(ctx.get("data_fim")) if ctx.get("data_fim") else "…")
    else:
        periodo = "Todos os lançamentos"
    cnv.setFont("Helvetica", 7.5)
    cnv.drawRightString(w - MARGEM, topo - 6,
                        "Emitido em %s às %s" % (ctx["emissao_data"], ctx["emissao_hora"]))
    cnv.drawRightString(w - MARGEM, topo - 17, periodo)

    cnv.setStrokeColor(GRAFITE)
    cnv.setLineWidth(1.3)
    cnv.line(MARGEM, topo - 34, w - MARGEM, topo - 34)

    ft = _filtros_ativos(ctx)
    if ft:
        cnv.setFont("Helvetica-Oblique", 7)
        cnv.setFillColor(CINZA_TXT)
        cnv.drawRightString(w - MARGEM, topo - 44, "Filtros: " + ft)


class _NumCanvas(_canvas.Canvas):
    """Adia o showPage p/ saber o total de páginas e estampar 'página X de Y'."""

    def __init__(self, *a, rodape="", **k):
        super().__init__(*a, **k)
        self._rodape = rodape
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self._rodape_fn(total)
            _canvas.Canvas.showPage(self)
        _canvas.Canvas.save(self)

    def _rodape_fn(self, total):
        w = A4[0]
        self.setFont("Helvetica", 7)
        self.setFillColor(CINZA_TXT)
        if self._rodape:
            self.drawString(MARGEM, 20, self._rodape)
        self.drawRightString(w - MARGEM, 20, "página %d de %d" % (self._pageNumber, total))


# ---------- corpo ----------
def _filtros_ativos(ctx):
    p = []
    if ctx["tipo"] == "entradas":
        s = {"paga": "paga (recebida)", "nao_paga": "não paga (a receber)"}.get(ctx.get("situacao"))
        if s:
            p.append("situação: " + s)
        return " · ".join(p)
    m = {"a_pagar": "a pagar", "vencido": "vencidas", "pago": "pagas"}
    if ctx.get("status"):
        p.append("situação: " + m.get(ctx["status"], ctx["status"]))
    if ctx.get("categoria_nome"):
        p.append("categoria: " + ctx["categoria_nome"])
    if ctx.get("forma_nome"):
        p.append("forma de pgto: " + ctx["forma_nome"])
    if ctx.get("fixo") == "1":
        p.append("só fixas mensais")
    elif ctx.get("fixo") == "0":
        p.append("sem as fixas")
    if ctx.get("busca"):
        p.append('descrição contém "%s"' % ctx["busca"])
    if ctx.get("base_data"):
        p.append("período pela data de " + ctx["base_data"])
    return " · ".join(p)


def _linha_item(s, oc):
    desc = "" if "descricao" in oc else escape(s.get("descricao") or "")
    if desc and s.get("fixo_mensal"):
        desc += ' <font color="#3a5a40">(fixa)</font>'
    return [
        Paragraph(desc, _desc),
        _p(s.get("numero_parcela") or "—", _cel_c),
        _p(_d(s.get("data_vencimento")), _cel_c),
        _p(_d(s.get("data_pagamento")), _cel_c),
        _p(_m(s.get("valor")), _cel_r),
        _p("" if "situacao" in oc else _sit(s), _cel_c),
    ]


def _walk(arv, nivel, oc, rows, sty, resumo=False):
    oc = oc + ([arv["chave"]] if arv["chave"] in ("descricao", "situacao") else [])
    for i, g in enumerate(arv["grupos"]):
        folha = not g.get("sub")
        if resumo and folha:
            # resumido: uma linha por grupo (rótulo + contagem + soma), sem parcelas.
            # 3 pesos, igual à tela: campo pequeno cinza · rótulo em negrito · (contagem) cinza
            rs = len(rows)
            rot = ('<font size="5.5" color="#5b6068">%s</font>  '
                   '<b><font color="#2b2b2b">%s</font></b>  '
                   '<font size="6" color="#5b6068">(%d lç · paga %s · em aberto %s)</font>') % (
                escape(arv["campo"].upper()), escape(g["rotulo"]), g["qtd"],
                _m(g["soma_paga"]), _m(g["soma_aberto"]))
            rows.append([Paragraph(rot, _cel), "", "", "",
                         _p(_m(g["soma"]), _sub_r), ""])
            sty += [
                ("SPAN", (0, rs), (3, rs)),
                ("LINEBELOW", (0, rs), (-1, rs), 0.4, CINZA_LINHA),
                ("LEFTPADDING", (0, rs), (0, rs), 5 + (nivel - 1) * 14),
            ]
            if i % 2:                       # zebra
                sty.append(("BACKGROUND", (0, rs), (-1, rs), colors.HexColor("#f6f7f9")))
            continue

        r = len(rows)
        rot = "%s   %s" % (arv["campo"].upper(), g["rotulo"])
        rows.append([_p(rot, _grp1 if nivel == 1 else _grp2), "", "", "", "", ""])
        sty += [
            ("SPAN", (0, r), (-1, r)),
            ("BACKGROUND", (0, r), (-1, r), CINZA_CAB1 if nivel == 1 else CINZA_CAB2),
            ("LINEABOVE", (0, r), (-1, r), 1 if nivel == 1 else 0.4,
             GRAFITE if nivel == 1 else CINZA_LINHA),
            ("TOPPADDING", (0, r), (-1, r), 5), ("BOTTOMPADDING", (0, r), (-1, r), 5),
            ("LEFTPADDING", (0, r), (0, r), 5 + (nivel - 1) * 14),
        ]
        if g.get("sub"):
            _walk(g["sub"], nivel + 1, oc, rows, sty, resumo)
        else:
            for s in g["itens"]:
                rows.append(_linha_item(s, oc))
        rs = len(rows)
        txt = "Subtotal  (%d lç · paga %s · em aberto %s)" % (
            g["qtd"], _m(g["soma_paga"]), _m(g["soma_aberto"]))
        rows.append([_p(txt, _sub_b if nivel == 1 else _sub), "", "", "",
                     _p(_m(g["soma"]), _sub_r), ""])
        sty += [
            ("SPAN", (0, rs), (3, rs)),
            ("BACKGROUND", (0, rs), (-1, rs), CINZA_SUB),
            ("LINEBELOW", (0, rs), (-1, rs), 0.4, CINZA_LINHA),
            ("LEFTPADDING", (0, rs), (0, rs), 5 + (nivel - 1) * 14),
        ]


def _tabela(ctx):
    resumo = ctx.get("modo") == "resumo"
    if resumo:
        rows = [[_p("Grupo", _th), "", "", "", _p("Valor", _th_r), ""]]
    else:
        rows = [[_p(c, _th_r if i == 4 else (_th_c if i else _th)) for i, c in enumerate(COLS)]]
    sty = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 1, GRAFITE),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5), ("TOPPADDING", (0, 0), (-1, 0), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.white]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, CINZA_LINHA),
    ]
    if resumo:
        sty += [("SPAN", (0, 0), (3, 0))]
    if ctx["arvore"]:
        _walk(ctx["arvore"], 1, [], rows, sty, resumo)
    elif not resumo:
        for s in ctx["linhas"]:
            rows.append(_linha_item(s, []))

    rz = ctx["resumo"]
    r = len(rows)
    txt = "TOTAL GERAL  (%d lç · paga %s · em aberto %s)" % (
        rz["qtd"], _m(rz["soma_paga"]), _m(rz["soma_aberto"]))
    rows.append([_p(txt, _tot), "", "", "", _p(_m(rz["soma"]), _tot_r), ""])
    sty += [
        ("SPAN", (0, r), (3, r)),
        ("LINEABOVE", (0, r), (-1, r), 1.4, GRAFITE),
        ("TOPPADDING", (0, r), (-1, r), 6), ("BOTTOMPADDING", (0, r), (-1, r), 6),
    ]
    t = Table(rows, colWidths=COL_W, repeatRows=1)
    t.setStyle(TableStyle(sty))
    return t


# ---------- relatório de ENTRADAS (repasses de comissão) ----------
COLS_ENT = ["Parcela", "Data", "Previsto", "Recebido", "Conf.", "Situação"]
COL_W_ENT = [96, 70, 92, 92, 60, 117]   # soma = 527


def _sit_ent(p):
    return "Paga" if p.get("paga") else "A receber"


def _linha_ent(p):
    parc = escape(str(p.get("parcela") or "—"))
    receb = _m(p["valor_recebido"]) if p.get("valor_recebido") is not None else "—"
    return [
        Paragraph(parc, _desc),
        _p(_d(p.get("data")), _cel_c),
        _p(_m(p.get("valor_previsto")), _cel_r),
        _p(receb, _cel_r),
        _p("Sim" if p.get("conferido_banco") else "Não", _cel_c),
        _p(_sit_ent(p), _cel_c),
    ]


def _sub_ent(rows, sty, nivel, texto, g, sufixo=""):
    rs = len(rows)
    txt = "%s  (%d parc · recebido %s · a receber %s)%s" % (
        texto, g["qtd"], _m(g["soma_paga"]), _m(g["soma_aberto"]), sufixo)
    rows.append([_p(txt, _sub_b if nivel == 1 else _sub), "", "",
                 _p(_m(g["soma"]), _sub_r), "", ""])
    sty += [
        ("SPAN", (0, rs), (2, rs)),
        ("LINEBELOW", (0, rs), (-1, rs), 0.4, CINZA_LINHA),
        ("LEFTPADDING", (0, rs), (0, rs), 5 + (nivel - 1) * 14),
    ]
    if nivel != 3:   # "Total da apólice" (nível 3) fica sem sombra; subtotais de grupo, sim
        sty.append(("BACKGROUND", (0, rs), (-1, rs), CINZA_SUB))


def _cab_ent(rows, sty, nivel, texto, fundo, regua):
    r = len(rows)
    st = _grp1 if nivel == 1 else _grp2
    rows.append([_p(texto, st), "", "", "", "", ""])
    sty += [
        ("SPAN", (0, r), (-1, r)),
        ("BACKGROUND", (0, r), (-1, r), fundo),
        ("LINEABOVE", (0, r), (-1, r), regua, GRAFITE if nivel == 1 else CINZA_LINHA),
        ("TOPPADDING", (0, r), (-1, r), 5), ("BOTTOMPADDING", (0, r), (-1, r), 5),
        ("LEFTPADDING", (0, r), (0, r), 5 + (nivel - 1) * 14),
    ]


def _walk_ent(node, nivel, rows, sty, modo="completo"):
    """Árvore de 0..2 níveis à escolha; a apólice é sempre a folha (nível 3).
    modo: completo · resumo (sem parcelas) · grupos (só os totais dos grupos —
    o grupo mais interno vira 1 linha, sem apólices)."""
    if node.get("campo"):
        fundo = CINZA_CAB1 if nivel == 1 else CINZA_CAB2
        regua = 1 if nivel == 1 else 0.4
        for i, g in enumerate(node["grupos"]):
            if modo == "grupos" and not g["sub"].get("campo"):
                rs = len(rows)
                txt = "%s  (%d parc · recebido %s · a receber %s)" % (
                    g["rotulo"], g["qtd"], _m(g["soma_paga"]), _m(g["soma_aberto"]))
                rows.append([_p(txt, _sub_b), "", "", _p(_m(g["soma"]), _sub_r), "", ""])
                sty += [("SPAN", (0, rs), (2, rs)),
                        ("LINEBELOW", (0, rs), (-1, rs), 0.4, CINZA_LINHA),
                        ("LEFTPADDING", (0, rs), (0, rs), 5 + (nivel - 1) * 14)]
                if i % 2:
                    sty.append(("BACKGROUND", (0, rs), (-1, rs), colors.HexColor("#f6f7f9")))
                continue
            rot = node["campo"].upper() + "   " + (g["rotulo"].upper() if nivel == 1 else g["rotulo"])
            _cab_ent(rows, sty, nivel, rot, fundo, regua)
            _walk_ent(g["sub"], nivel + 1, rows, sty, modo)
            _sub_ent(rows, sty, nivel, "Subtotal " + g["rotulo"], g)
        return
    if modo == "grupos":
        return
    # apólice só ganha sombra no cabeçalho quando é o nível de topo (sem agrupamento);
    # aninhada sob um grupo, fica sem sombra — a sombra é do grupo
    fundo_ap = CINZA_CAB2 if nivel == 1 else colors.white
    for ap in node["apolices"]:
        pct = ("%s%%" % formatar_numero(ap["comissao_percentual"])
               if ap.get("comissao_percentual") is not None else "—")
        cab = "%s   ·   apólice %s   ·   prêmio líquido %s   ·   comissão %s" % (
            ap["cliente_nome"], ap.get("numero_apolice") or "—",
            _m(ap.get("premio_liquido")), pct)
        _cab_ent(rows, sty, 3, cab, fundo_ap, 0.4)
        if ap.get("divergencia"):
            det = " · ".join(
                "%s: sistema %s · relatório %s" % (d["campo"], _m(d["sistema"]), _m(d["relatorio"]))
                for d in ap["divergencia"])
            r = len(rows)
            rows.append([_p("⚠ Divergência com o relatório da corretora — " + det, _sub),
                         "", "", "", "", ""])
            sty += [("SPAN", (0, r), (-1, r)),
                    ("TEXTCOLOR", (0, r), (-1, r), colors.HexColor("#b26a00")),
                    ("LEFTPADDING", (0, r), (0, r), 33)]
        if modo == "completo":
            for p in ap["parcelas"]:
                rows.append(_linha_ent(p))
        _sub_ent(rows, sty, 3, "Total da apólice", ap,
                 sufixo=" — COCORRETAGEM" if ap.get("cocorretagem") else "")


def _tabela_entradas(ctx):
    rows = [[_p(c, _th_r if i in (2, 3) else (_th_c if i else _th))
             for i, c in enumerate(COLS_ENT)]]
    sty = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 1, GRAFITE),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5), ("TOPPADDING", (0, 0), (-1, 0), 2),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, CINZA_LINHA),
    ]
    _walk_ent(ctx["arvore"], 1, rows, sty, ctx.get("modo") or "completo")

    rz = ctx["resumo"]
    r = len(rows)
    txt = "TOTAL GERAL  (%d apólice(s) · %d parc · recebido %s · a receber %s)" % (
        rz["qtd_apolices"], rz["qtd"], _m(rz["soma_paga"]), _m(rz["soma_aberto"]))
    rows.append([_p(txt, _tot), "", "", _p(_m(rz["soma"]), _tot_r), "", ""])
    sty += [
        ("SPAN", (0, r), (2, r)),
        ("LINEABOVE", (0, r), (-1, r), 1.4, GRAFITE),
        ("TOPPADDING", (0, r), (-1, r), 6), ("BOTTOMPADDING", (0, r), (-1, r), 6),
    ]
    t = Table(rows, colWidths=COL_W_ENT, repeatRows=1)
    t.setStyle(TableStyle(sty))
    return t


def gerar(ctx):
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM,
        topMargin=MARGEM + 52, bottomMargin=MARGEM + 6,
        title=ctx["titulo"], author="Plenus")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="corpo")
    doc.addPageTemplates([PageTemplate(
        id="pt", frames=[frame], onPage=lambda cnv, d: _cabecalho(cnv, d, ctx))])

    # "Filtros: …" é desenhado no cabeçalho (à direita, sob a régua) — não vai no story
    entradas = ctx["tipo"] == "entradas"
    story = []
    if not ctx["linhas"]:
        vazio = ("Nenhuma parcela de repasse no período/filtro escolhido." if entradas
                 else "Nenhum lançamento no período/filtro escolhido.")
        story.append(_p(vazio, _vazio))
    else:
        story.append(_tabela_entradas(ctx) if entradas else _tabela(ctx))

    rodape = "Plenus · emitido em %s às %s" % (ctx["emissao_data"], ctx["emissao_hora"])
    doc.build(story, canvasmaker=lambda *a, **k: _NumCanvas(*a, rodape=rodape, **k))
    return buf.getvalue()
