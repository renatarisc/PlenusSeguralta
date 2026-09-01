"""Consultas ao banco, por entidade. Cresce junto com o sistema.

Cada função abre sua própria conexão (via db.conexao) e devolve dicts / listas de dicts.
"""

import unicodedata

from db import conexao, fazer_backup
from validacao import so_digitos, para_decimal, dias_ate_data


def _int_ou_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _sem_acento_minusculo(texto):
    """Normaliza p/ busca: minúsculo e sem acento ('José' -> 'jose')."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()

# ---------- cliente ----------

_COLS_CLIENTE = (
    "nome", "data_nascimento", "sexo", "cpf",
    "end_rua", "end_numero", "end_complemento", "end_bairro", "end_cep", "end_cidade", "end_estado",
    "tel_ddd", "tel_numero", "email",
)


def _valores_cliente(dados):
    valores = []
    for col in _COLS_CLIENTE:
        v = (dados.get(col) or "").strip()
        if col in ("cpf", "end_cep", "tel_ddd", "tel_numero"):
            v = so_digitos(v)
        valores.append(v or None)
    return valores


def listar_clientes(busca=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT id, nome, cpf, end_cidade, end_estado, tel_ddd, tel_numero, email "
            "FROM cliente ORDER BY nome COLLATE NOCASE"
        ).fetchall()]

    termo = (busca or "").strip()
    if not termo:
        return linhas

    # filtro em Python: nome sem acento/maiúsculas; CPF só se a busca tiver dígitos
    alvo = _sem_acento_minusculo(termo)
    digitos = so_digitos(termo)
    return [
        c for c in linhas
        if alvo in _sem_acento_minusculo(c["nome"])
        or (digitos and digitos in (c["cpf"] or ""))
    ]


def obter_cliente(cliente_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM cliente WHERE id = ?", (cliente_id,)).fetchone()
        return dict(l) if l else None


def criar_cliente(dados):
    with conexao() as con:
        marc = ", ".join("?" for _ in _COLS_CLIENTE)
        cur = con.execute(
            f"INSERT INTO cliente ({', '.join(_COLS_CLIENTE)}) VALUES ({marc})",
            _valores_cliente(dados),
        )
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def atualizar_cliente(cliente_id, dados):
    with conexao() as con:
        atrib = ", ".join(f"{c} = ?" for c in _COLS_CLIENTE)
        con.execute(
            f"UPDATE cliente SET {atrib}, atualizado_em = datetime('now') WHERE id = ?",
            _valores_cliente(dados) + [cliente_id],
        )
    fazer_backup()


def excluir_cliente(cliente_id):
    with conexao() as con:
        con.execute("DELETE FROM cliente WHERE id = ?", (cliente_id,))
    fazer_backup()


# ---------- cadastros simples (tipo_seguro, forma_pagamento) - só nome ----------

_TABELAS_SIMPLES = {"tipo_seguro", "forma_pagamento", "seguradora"}


def listar_simples(tabela):
    assert tabela in _TABELAS_SIMPLES
    with conexao() as con:
        return [dict(l) for l in con.execute(
            f"SELECT id, nome FROM {tabela} ORDER BY nome COLLATE NOCASE"
        ).fetchall()]


def criar_simples(tabela, nome):
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome:
        return None
    with conexao() as con:
        cur = con.execute(f"INSERT INTO {tabela} (nome) VALUES (?)", (nome,))
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def renomear_simples(tabela, item_id, nome):
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome:
        return
    with conexao() as con:
        con.execute(f"UPDATE {tabela} SET nome = ? WHERE id = ?", (nome, item_id))
    fazer_backup()


def excluir_simples(tabela, item_id):
    assert tabela in _TABELAS_SIMPLES
    with conexao() as con:
        con.execute(f"DELETE FROM {tabela} WHERE id = ?", (item_id,))
    fazer_backup()


# ---------- apólice (+ parcelas) ----------

_COLS_APOLICE = (
    "cliente_id", "seguradora_id", "tipo_seguro_id", "numero_apolice",
    "vigencia_inicio", "vigencia_fim",
    "premio_liquido", "forma_pagamento_id", "comissao_percentual", "comissao_valor",
    "lancado_quiver", "link_onedrive",
)


def _valores_apolice(dados):
    return [
        _int_ou_none(dados.get("cliente_id")),
        _int_ou_none(dados.get("seguradora_id")),
        _int_ou_none(dados.get("tipo_seguro_id")),
        (dados.get("numero_apolice") or "").strip() or None,
        (dados.get("vigencia_inicio") or "").strip() or None,
        (dados.get("vigencia_fim") or "").strip() or None,
        para_decimal(dados.get("premio_liquido")),
        _int_ou_none(dados.get("forma_pagamento_id")),
        para_decimal(dados.get("comissao_percentual")),
        para_decimal(dados.get("comissao_valor")),
        1 if str(dados.get("lancado_quiver", "")).strip().lower() in ("1", "sim", "on", "true") else 0,
        (dados.get("link_onedrive") or "").strip() or None,
    ]


def _inserir_parcelas(con, apolice_id, parcelas):
    for p in parcelas or []:
        con.execute(
            "INSERT INTO apolice_parcela (apolice_id, identificacao, data, valor) VALUES (?, ?, ?, ?)",
            (apolice_id, p.get("identificacao"), p.get("data"), p.get("valor")),
        )


def listar_apolices(cliente_id=None):
    sql = """SELECT a.id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
                    a.premio_liquido, a.lancado_quiver,
                    c.nome AS cliente_nome, t.nome AS tipo_seguro_nome,
                    s.nome AS seguradora_nome
               FROM apolice a
               LEFT JOIN cliente c     ON c.id = a.cliente_id
               LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id
               LEFT JOIN seguradora s  ON s.id = a.seguradora_id"""
    params = ()
    if cliente_id:
        sql += " WHERE a.cliente_id = ?"
        params = (cliente_id,)
    sql += " ORDER BY a.criado_em DESC, a.id DESC"
    with conexao() as con:
        return [dict(l) for l in con.execute(sql, params).fetchall()]


def contar_apolices_do_cliente(cliente_id):
    with conexao() as con:
        return con.execute("SELECT COUNT(*) FROM apolice WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]


def apolices_por_vencer(limite_dias):
    """Apólices com vigência a <= limite_dias do fim (inclui as já vencidas), da mais urgente
    pra menos. Cada item ganha o campo dias_restantes (negativo = já venceu)."""
    itens = []
    for a in listar_apolices():
        d = dias_ate_data(a.get("vigencia_fim"))
        if d is not None and d <= limite_dias:
            a["dias_restantes"] = d
            itens.append(a)
    itens.sort(key=lambda x: x["dias_restantes"])
    return itens


def contar_apolices_por_vencer(limite_dias):
    with conexao() as con:
        return con.execute(
            "SELECT COUNT(*) FROM apolice "
            "WHERE vigencia_fim IS NOT NULL AND vigencia_fim <> '' "
            "  AND vigencia_fim <= date('now', 'localtime', ?)",
            (f"+{int(limite_dias)} days",),
        ).fetchone()[0]


def obter_apolice(apolice_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM apolice WHERE id = ?", (apolice_id,)).fetchone()
        if not l:
            return None
        ap = dict(l)
        ap["parcelas"] = [dict(p) for p in con.execute(
            "SELECT id, identificacao, data, valor FROM apolice_parcela "
            "WHERE apolice_id = ? ORDER BY COALESCE(data, ''), id",
            (apolice_id,),
        ).fetchall()]
        return ap


def criar_apolice(dados, parcelas):
    with conexao() as con:
        marcadores = ", ".join("?" for _ in _COLS_APOLICE)
        cur = con.execute(
            f"INSERT INTO apolice ({', '.join(_COLS_APOLICE)}) VALUES ({marcadores})",
            _valores_apolice(dados),
        )
        novo_id = cur.lastrowid
        _inserir_parcelas(con, novo_id, parcelas)
    fazer_backup()
    return novo_id


def atualizar_apolice(apolice_id, dados, parcelas):
    with conexao() as con:
        atrib = ", ".join(f"{c} = ?" for c in _COLS_APOLICE)
        con.execute(
            f"UPDATE apolice SET {atrib}, atualizado_em = datetime('now') WHERE id = ?",
            _valores_apolice(dados) + [apolice_id],
        )
        con.execute("DELETE FROM apolice_parcela WHERE apolice_id = ?", (apolice_id,))
        _inserir_parcelas(con, apolice_id, parcelas)
    fazer_backup()


def excluir_apolice(apolice_id):
    with conexao() as con:
        con.execute("DELETE FROM apolice WHERE id = ?", (apolice_id,))
    fazer_backup()


# ---------- avisos de vencimento (WhatsApp) ----------

def notificacao_ja_enviada(apolice_id, marco, vigencia_fim):
    with conexao() as con:
        r = con.execute(
            "SELECT 1 FROM notificacao_vencimento WHERE apolice_id = ? AND marco = ? AND vigencia_fim IS ?",
            (apolice_id, marco, vigencia_fim),
        ).fetchone()
        return r is not None


def registrar_notificacao(apolice_id, marco, vigencia_fim, canal, destino, resultado):
    with conexao() as con:
        con.execute(
            """INSERT OR REPLACE INTO notificacao_vencimento
                   (apolice_id, marco, vigencia_fim, canal, destino, resultado, enviado_em)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (apolice_id, marco, vigencia_fim, canal, destino, resultado),
        )
    fazer_backup()
