"""Consultas ao banco, por entidade. Cresce junto com o sistema.

Cada função abre sua própria conexão (via db.conexao) e devolve dicts / listas de dicts.
"""

import unicodedata

from db import conexao, fazer_backup
from validacao import so_digitos, para_decimal, dias_ate_data
from seguranca import hash_senha, senha_confere


# ---------- usuários (login) ----------

_COLS_USUARIO_PUB = "id, nome, login, ativo, criado_em, ultimo_acesso"


def contar_usuarios():
    with conexao() as con:
        return con.execute("SELECT COUNT(*) FROM usuario").fetchone()[0]


def listar_usuarios():
    with conexao() as con:
        return [dict(l) for l in con.execute(
            f"SELECT {_COLS_USUARIO_PUB} FROM usuario ORDER BY nome COLLATE NOCASE"
        ).fetchall()]


def obter_usuario(uid):
    with conexao() as con:
        l = con.execute(f"SELECT {_COLS_USUARIO_PUB} FROM usuario WHERE id = ?", (uid,)).fetchone()
        return dict(l) if l else None


def autenticar(login, senha):
    """Devolve {id, nome, login} se ok e ativo; senão None. Marca ultimo_acesso."""
    login = (login or "").strip()
    with conexao() as con:
        u = con.execute("SELECT * FROM usuario WHERE login = ? COLLATE NOCASE", (login,)).fetchone()
        if not u or not u["ativo"] or not senha_confere(senha, u["senha_hash"]):
            return None
        con.execute("UPDATE usuario SET ultimo_acesso = datetime('now') WHERE id = ?", (u["id"],))
    return {"id": u["id"], "nome": u["nome"], "login": u["login"]}


def login_em_uso(login, ignorar_id=None):
    with conexao() as con:
        r = con.execute(
            "SELECT id FROM usuario WHERE login = ? COLLATE NOCASE AND id IS NOT ?",
            ((login or "").strip(), ignorar_id),
        ).fetchone()
        return r is not None


def criar_usuario(nome, login, senha):
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO usuario (nome, login, senha_hash) VALUES (?, ?, ?)",
            ((nome or "").strip(), (login or "").strip(), hash_senha(senha)),
        )
        novo = cur.lastrowid
    fazer_backup()
    return novo


def atualizar_usuario(uid, nome, login, ativo, senha=None):
    campos = "nome = ?, login = ?, ativo = ?"
    valores = [(nome or "").strip(), (login or "").strip(), 1 if ativo else 0]
    if senha:
        campos += ", senha_hash = ?"
        valores.append(hash_senha(senha))
    valores.append(uid)
    with conexao() as con:
        con.execute(f"UPDATE usuario SET {campos} WHERE id = ?", valores)
    fazer_backup()


def excluir_usuario(uid):
    with conexao() as con:
        con.execute("DELETE FROM usuario WHERE id = ?", (uid,))
    fazer_backup()


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


def listar_clientes(busca=None, uf=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT id, nome, cpf, end_cidade, end_estado, tel_ddd, tel_numero, email "
            "FROM cliente ORDER BY nome COLLATE NOCASE"
        ).fetchall()]

    if uf:
        linhas = [c for c in linhas if (c["end_estado"] or "") == uf]

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


def ufs_dos_clientes():
    with conexao() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT end_estado FROM cliente "
            "WHERE end_estado IS NOT NULL AND end_estado <> '' ORDER BY end_estado"
        ).fetchall()]


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


def obter_simples(tabela, item_id):
    assert tabela in _TABELAS_SIMPLES
    with conexao() as con:
        l = con.execute(f"SELECT id, nome FROM {tabela} WHERE id = ?", (item_id,)).fetchone()
        return dict(l) if l else None


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
    "premio_liquido", "iof", "premio_total",
    "forma_pagamento_id", "comissao_percentual", "comissao_valor",
    "lancado_quiver", "link_onedrive",
    "veiculo_placa", "veiculo_descricao",
    "apolice_enviada", "apolice_enviada_data", "cartao_enviado", "cartao_enviado_data",
)


def _sim_nao(v):
    return 1 if str(v or "").strip().lower() in ("1", "sim", "on", "true") else 0


def _valores_apolice(dados):
    return [
        _int_ou_none(dados.get("cliente_id")),
        _int_ou_none(dados.get("seguradora_id")),
        _int_ou_none(dados.get("tipo_seguro_id")),
        (dados.get("numero_apolice") or "").strip() or None,
        (dados.get("vigencia_inicio") or "").strip() or None,
        (dados.get("vigencia_fim") or "").strip() or None,
        para_decimal(dados.get("premio_liquido")),
        para_decimal(dados.get("iof")),
        para_decimal(dados.get("premio_total")),
        _int_ou_none(dados.get("forma_pagamento_id")),
        para_decimal(dados.get("comissao_percentual")),
        para_decimal(dados.get("comissao_valor")),
        _sim_nao(dados.get("lancado_quiver")),
        (dados.get("link_onedrive") or "").strip() or None,
        (dados.get("veiculo_placa") or "").strip().upper() or None,
        (dados.get("veiculo_descricao") or "").strip() or None,
        _sim_nao(dados.get("apolice_enviada")),
        (dados.get("apolice_enviada_data") or "").strip() or None,
        _sim_nao(dados.get("cartao_enviado")),
        (dados.get("cartao_enviado_data") or "").strip() or None,
    ]


def _inserir_parcelas(con, apolice_id, parcelas):
    for p in parcelas or []:
        con.execute(
            "INSERT INTO apolice_parcela (apolice_id, identificacao, data, valor) VALUES (?, ?, ?, ?)",
            (apolice_id, p.get("identificacao"), p.get("data"), p.get("valor")),
        )


def listar_apolices(cliente_id=None, tipo_seguro_id=None, mes_inicio=None, quiver=None, busca=None):
    sql = """SELECT a.id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
                    a.premio_liquido, a.lancado_quiver,
                    c.nome AS cliente_nome, t.nome AS tipo_seguro_nome,
                    s.nome AS seguradora_nome
               FROM apolice a
               LEFT JOIN cliente c     ON c.id = a.cliente_id
               LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id
               LEFT JOIN seguradora s  ON s.id = a.seguradora_id"""
    filtros, params = [], []
    if cliente_id:
        filtros.append("a.cliente_id = ?")
        params.append(cliente_id)
    if tipo_seguro_id:
        filtros.append("a.tipo_seguro_id = ?")
        params.append(tipo_seguro_id)
    if mes_inicio:
        filtros.append("substr(a.vigencia_inicio, 6, 2) = ?")
        params.append(f"{int(mes_inicio):02d}")
    if quiver in (0, 1, True, False):
        filtros.append("COALESCE(a.lancado_quiver, 0) = ?")
        params.append(1 if quiver in (1, True) else 0)
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY a.criado_em DESC, a.id DESC"
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(sql, params).fetchall()]

    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [
            a for a in linhas
            if alvo in _sem_acento_minusculo(a.get("cliente_nome") or "")
            or alvo in _sem_acento_minusculo(a.get("numero_apolice") or "")
        ]
    return linhas


def contar_apolices_do_cliente(cliente_id):
    with conexao() as con:
        return con.execute("SELECT COUNT(*) FROM apolice WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]


# ---------- números do painel ----------

def resumo_painel():
    with conexao() as con:
        um = lambda sql: con.execute(sql).fetchone()[0]
        return {
            "clientes": um("SELECT COUNT(*) FROM cliente"),
            "apolices": um("SELECT COUNT(*) FROM apolice"),
            "seguradoras": um("SELECT COUNT(*) FROM seguradora"),
            "premio_liquido_total": um("SELECT COALESCE(SUM(premio_liquido), 0) FROM apolice"),
            "quiver_sim": um("SELECT COUNT(*) FROM apolice WHERE COALESCE(lancado_quiver, 0) = 1"),
        }


def apolices_por_tipo():
    """[{nome, qtd}] ordenado da maior qtd pra menor; apólice sem tipo vira '(sem tipo)'."""
    with conexao() as con:
        linhas = con.execute(
            "SELECT COALESCE(t.nome, '(sem tipo)') AS nome, COUNT(*) AS qtd "
            "  FROM apolice a LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            " GROUP BY COALESCE(t.nome, '(sem tipo)') "
            " ORDER BY qtd DESC, nome COLLATE NOCASE"
        ).fetchall()
        return [dict(l) for l in linhas]


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


# ---------- avisos de boleto (parcela a vencer) ----------

_SQL_PARCELAS_BOLETO = """
SELECT p.id AS parcela_id, p.identificacao, p.data, p.valor,
       a.id AS apolice_id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
       c.nome AS cliente_nome, s.nome AS seguradora_nome, t.nome AS tipo_seguro_nome,
       f.nome AS forma_pagamento_nome
  FROM apolice_parcela p
  JOIN apolice a          ON a.id = p.apolice_id
  LEFT JOIN cliente c     ON c.id = a.cliente_id
  LEFT JOIN seguradora s  ON s.id = a.seguradora_id
  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id
  JOIN forma_pagamento f  ON f.id = a.forma_pagamento_id
 WHERE lower(f.nome) LIKE '%boleto%'
   AND p.data IS NOT NULL AND p.data <> ''
"""


def parcelas_boleto_pendentes():
    """Todas as parcelas de apólices com forma de pagamento 'boleto' (com data)."""
    with conexao() as con:
        return [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO + " ORDER BY p.data").fetchall()]


def parcelas_boleto_a_vencer(limite_dias):
    """Parcelas de boleto vencendo em <= limite_dias (inclui as já vencidas), mais urgente
    primeiro. Cada item ganha dias_restantes (negativo = já venceu)."""
    itens = []
    for p in parcelas_boleto_pendentes():
        d = dias_ate_data(p.get("data"))
        if d is not None and d <= limite_dias:
            p["dias_restantes"] = d
            itens.append(p)
    itens.sort(key=lambda x: x["dias_restantes"])
    return itens


def contar_parcelas_boleto_a_vencer(limite_dias):
    return len(parcelas_boleto_a_vencer(limite_dias))


def notificacao_parcela_ja_enviada(parcela_id, marco, data_venc):
    with conexao() as con:
        r = con.execute(
            "SELECT 1 FROM notificacao_parcela WHERE parcela_id = ? AND marco = ? AND data_vencimento IS ?",
            (parcela_id, marco, data_venc),
        ).fetchone()
        return r is not None


def registrar_notificacao_parcela(parcela_id, marco, data_venc, canal, destino, resultado):
    with conexao() as con:
        con.execute(
            """INSERT OR REPLACE INTO notificacao_parcela
                   (parcela_id, marco, data_vencimento, canal, destino, resultado, enviado_em)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (parcela_id, marco, data_venc, canal, destino, resultado),
        )
    fazer_backup()
