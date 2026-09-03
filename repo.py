"""Consultas ao banco, por entidade. Cresce junto com o sistema.

Cada função abre sua própria conexão (via db.conexao) e devolve dicts / listas de dicts.
"""

import secrets
import unicodedata
from datetime import date

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

_TABELAS_SIMPLES = {"tipo_seguro", "forma_pagamento", "seguradora", "categoria_saida"}


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


def nome_simples_existe(tabela, nome, ignorar_id=None):
    """True se já há um registro com esse nome (sem diferenciar maiúsc./acentuação de caixa)."""
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome:
        return False
    sql = f"SELECT 1 FROM {tabela} WHERE nome = ? COLLATE NOCASE"
    params = [nome]
    if ignorar_id:
        sql += " AND id <> ?"
        params.append(ignorar_id)
    with conexao() as con:
        return con.execute(sql, params).fetchone() is not None


def criar_simples(tabela, nome):
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome or nome_simples_existe(tabela, nome):
        return None
    with conexao() as con:
        cur = con.execute(f"INSERT INTO {tabela} (nome) VALUES (?)", (nome,))
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def renomear_simples(tabela, item_id, nome):
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome or nome_simples_existe(tabela, nome, ignorar_id=item_id):
        return False
    with conexao() as con:
        con.execute(f"UPDATE {tabela} SET nome = ? WHERE id = ?", (nome, item_id))
    fazer_backup()
    return True


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
    "forma_pagamento_id", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_plenus_recebido", "plenus_conferido_banco",
    "comissao_parcelada", "comissao_cocorretagem",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive",
    "veiculo_placa", "veiculo_descricao",
    "aviso_vigencia_ok", "aviso_vigencia_ok_em",
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
        para_decimal(dados.get("comissao_valor_seguralta_receber")),
        para_decimal(dados.get("comissao_valor_plenus_receber")),
        para_decimal(dados.get("comissao_valor_seguralta_recebido")),
        para_decimal(dados.get("comissao_valor_plenus_recebido")),
        (dados.get("data_plenus_recebido") or "").strip() or None,
        _sim_nao(dados.get("plenus_conferido_banco")),
        _sim_nao(dados.get("comissao_parcelada")),
        _sim_nao(dados.get("comissao_cocorretagem")),
        para_decimal(dados.get("previsto_relatorio_seguralta")),
        para_decimal(dados.get("recebido_relatorio_seguralta")),
        para_decimal(dados.get("previsto_relatorio_plenus")),
        para_decimal(dados.get("recebido_relatorio_plenus")),
        _sim_nao(dados.get("lancado_quiver")),
        (dados.get("link_onedrive") or "").strip() or None,
        (dados.get("veiculo_placa") or "").strip().upper() or None,
        (dados.get("veiculo_descricao") or "").strip() or None,
        _sim_nao(dados.get("aviso_vigencia_ok")),
        (dados.get("aviso_vigencia_ok_em") or "").strip() or None,
        _sim_nao(dados.get("apolice_enviada")),
        (dados.get("apolice_enviada_data") or "").strip() or None,
        _sim_nao(dados.get("cartao_enviado")),
        (dados.get("cartao_enviado_data") or "").strip() or None,
    ]


def _inserir_parcelas(con, apolice_id, parcelas):
    hoje = date.today().isoformat()
    for p in parcelas or []:
        paga = 1 if p.get("paga") in (1, "1", True, "sim", "on") else 0
        pago_em = (p.get("pago_em") or "").strip() or (hoje if paga else None)
        aviso = 1 if p.get("aviso_ok") in (1, "1", True, "sim", "on") else 0
        aviso_em = (p.get("aviso_ok_em") or "").strip() or (hoje if aviso else None)
        con.execute(
            "INSERT INTO apolice_parcela "
            "(apolice_id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (apolice_id, p.get("identificacao"), p.get("data"), p.get("valor"),
             paga, pago_em, aviso, aviso_em),
        )


def _inserir_comissoes(con, apolice_id, linhas):
    for i, c in enumerate(linhas or []):
        con.execute(
            "INSERT INTO apolice_comissao "
            "(apolice_id, parcela, valor_previsto, valor_recebido, data, ordem) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (apolice_id, c.get("parcela"), c.get("valor_previsto"),
             c.get("valor_recebido"), c.get("data"), i),
        )


def _inserir_repasses(con, apolice_id, linhas):
    for i, r in enumerate(linhas or []):
        conf = 1 if r.get("conferido_banco") in (1, "1", True, "sim", "on") else 0
        con.execute(
            "INSERT INTO apolice_repasse "
            "(apolice_id, parcela, valor_previsto, valor_recebido, data, conferido_banco, ordem) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (apolice_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), conf, i),
        )


def listar_apolices(cliente_id=None, tipo_seguro_id=None, mes_inicio=None, quiver=None,
                    busca=None, parcela_status=None):
    sql = """SELECT a.id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
                    a.premio_liquido, a.lancado_quiver, a.aviso_vigencia_ok,
                    c.nome AS cliente_nome, t.nome AS tipo_seguro_nome,
                    s.nome AS seguradora_nome,
                    (SELECT p.data FROM apolice_parcela p
                       WHERE p.apolice_id = a.id AND COALESCE(p.paga, 0) = 0 AND p.data IS NOT NULL
                       ORDER BY p.data LIMIT 1) AS proxima_parcela_data,
                    (SELECT p.valor FROM apolice_parcela p
                       WHERE p.apolice_id = a.id AND COALESCE(p.paga, 0) = 0 AND p.data IS NOT NULL
                       ORDER BY p.data LIMIT 1) AS proxima_parcela_valor
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

    if parcela_status:
        def _combina(a):
            pd = a.get("proxima_parcela_data")
            d = dias_ate_data(pd) if pd else None
            if parcela_status == "vencida":
                return d is not None and d < 0
            if parcela_status == "proxima":
                return d is not None and 0 <= d <= 10
            if parcela_status == "sem":
                return pd is None
            return True
        linhas = [a for a in linhas if _combina(a)]
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


def apolices_por_vencer(limite_dias, incluir_avisadas=False):
    """Apólices com vigência a <= limite_dias do fim (inclui as já vencidas), da mais urgente
    pra menos. Cada item ganha `dias_restantes` (negativo = já venceu). Por padrão esconde
    as que já foram marcadas como 'cliente avisado'."""
    itens = []
    for a in listar_apolices():
        if not incluir_avisadas and a.get("aviso_vigencia_ok"):
            continue
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
            "SELECT id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em "
            "FROM apolice_parcela WHERE apolice_id = ? ORDER BY COALESCE(data, ''), id",
            (apolice_id,),
        ).fetchall()]
        ap["comissoes"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data "
            "FROM apolice_comissao WHERE apolice_id = ? ORDER BY ordem, id",
            (apolice_id,),
        ).fetchall()]
        ap["repasses"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data, conferido_banco "
            "FROM apolice_repasse WHERE apolice_id = ? ORDER BY ordem, id",
            (apolice_id,),
        ).fetchall()]
        return ap


def marcar_parcela_paga(parcela_id, paga):
    with conexao() as con:
        con.execute(
            "UPDATE apolice_parcela SET paga = ?, pago_em = ? WHERE id = ?",
            (1 if paga else 0, date.today().isoformat() if paga else None, parcela_id),
        )
    fazer_backup()


def marcar_aviso_parcela(parcela_id, ok):
    with conexao() as con:
        con.execute(
            "UPDATE apolice_parcela SET aviso_ok = ?, aviso_ok_em = ? WHERE id = ?",
            (1 if ok else 0, date.today().isoformat() if ok else None, parcela_id),
        )
    fazer_backup()


def marcar_aviso_vigencia(apolice_id, ok):
    with conexao() as con:
        con.execute(
            "UPDATE apolice SET aviso_vigencia_ok = ?, aviso_vigencia_ok_em = ? WHERE id = ?",
            (1 if ok else 0, date.today().isoformat() if ok else None, apolice_id),
        )
    fazer_backup()


def criar_apolice(dados, parcelas, comissoes=None, repasses=None):
    with conexao() as con:
        marcadores = ", ".join("?" for _ in _COLS_APOLICE)
        cur = con.execute(
            f"INSERT INTO apolice ({', '.join(_COLS_APOLICE)}) VALUES ({marcadores})",
            _valores_apolice(dados),
        )
        novo_id = cur.lastrowid
        _inserir_parcelas(con, novo_id, parcelas)
        _inserir_comissoes(con, novo_id, comissoes)
        _inserir_repasses(con, novo_id, repasses)
    fazer_backup()
    return novo_id


def atualizar_apolice(apolice_id, dados, parcelas, comissoes=None, repasses=None):
    with conexao() as con:
        atrib = ", ".join(f"{c} = ?" for c in _COLS_APOLICE)
        con.execute(
            f"UPDATE apolice SET {atrib}, atualizado_em = datetime('now') WHERE id = ?",
            _valores_apolice(dados) + [apolice_id],
        )
        con.execute("DELETE FROM apolice_parcela WHERE apolice_id = ?", (apolice_id,))
        _inserir_parcelas(con, apolice_id, parcelas)
        con.execute("DELETE FROM apolice_comissao WHERE apolice_id = ?", (apolice_id,))
        _inserir_comissoes(con, apolice_id, comissoes)
        con.execute("DELETE FROM apolice_repasse WHERE apolice_id = ?", (apolice_id,))
        _inserir_repasses(con, apolice_id, repasses)
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


# marco 0 = "aviso diário até o cliente ser avisado" (o e-mail usa isto no lugar dos marcos)

def email_vigencia_enviado_hoje(apolice_id):
    with conexao() as con:
        r = con.execute(
            "SELECT 1 FROM notificacao_vencimento "
            "WHERE apolice_id = ? AND marco = 0 AND date(enviado_em) = date('now', 'localtime')",
            (apolice_id,),
        ).fetchone()
        return r is not None


def email_boleto_enviado_hoje(parcela_id):
    with conexao() as con:
        r = con.execute(
            "SELECT 1 FROM notificacao_parcela "
            "WHERE parcela_id = ? AND marco = 0 AND date(enviado_em) = date('now', 'localtime')",
            (parcela_id,),
        ).fetchone()
        return r is not None


# ---------- avisos de boleto (parcela a vencer) ----------

_SQL_PARCELAS_BOLETO = """
SELECT p.id AS parcela_id, p.identificacao, p.data, p.valor, p.aviso_ok,
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
   AND COALESCE(p.paga, 0) = 0
"""


def parcelas_boleto_pendentes():
    """Todas as parcelas de apólices com forma de pagamento 'boleto' (com data)."""
    with conexao() as con:
        return [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO + " ORDER BY p.data").fetchall()]


def parcelas_boleto_a_vencer(limite_dias, incluir_avisadas=False):
    """Parcelas de boleto vencendo em <= limite_dias (inclui as já vencidas), mais urgente
    primeiro. Por padrão esconde as que já foram marcadas como 'cliente avisado'."""
    itens = []
    for p in parcelas_boleto_pendentes():
        if not incluir_avisadas and p.get("aviso_ok"):
            continue
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


# ---------- eventos do Google Agenda ----------

def evento_agenda_obter(chave):
    with conexao() as con:
        l = con.execute("SELECT * FROM evento_agenda WHERE chave = ?", (chave,)).fetchone()
        return dict(l) if l else None


def evento_agenda_salvar(chave, event_id, data_ref, resumo):
    with conexao() as con:
        con.execute(
            """INSERT INTO evento_agenda (chave, event_id, data_ref, resumo, atualizado_em)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(chave) DO UPDATE SET
                   event_id = excluded.event_id, data_ref = excluded.data_ref,
                   resumo = excluded.resumo, atualizado_em = datetime('now')""",
            (chave, event_id, data_ref, resumo),
        )
    fazer_backup()


def evento_agenda_remover(chave):
    with conexao() as con:
        con.execute("DELETE FROM evento_agenda WHERE chave = ?", (chave,))
    fazer_backup()


def eventos_agenda_todos():
    with conexao() as con:
        return [dict(l) for l in con.execute("SELECT chave, event_id FROM evento_agenda").fetchall()]


# ---------- fluxo de caixa: saídas ----------

_COLS_SAIDA = ("descricao", "categoria_id", "forma_pagamento_id", "valor",
               "data_vencimento", "data_pagamento", "numero_parcela", "fixo_mensal", "serie_id")


def _para_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _valores_saida(dados):
    return [
        (dados.get("descricao") or "").strip() or None,
        _para_int(dados.get("categoria_id")),
        _para_int(dados.get("forma_pagamento_id")),
        para_decimal(dados.get("valor")),
        (dados.get("data_vencimento") or "").strip() or None,
        (dados.get("data_pagamento") or "").strip() or None,
        (dados.get("numero_parcela") or "").strip() or None,
        1 if str(dados.get("fixo_mensal") or "").strip() in ("1", "sim", "on", "true") else 0,
        (dados.get("serie_id") or "").strip() or None,
    ]


def _inserir_saida(con, dados):
    marc = ", ".join("?" for _ in _COLS_SAIDA)
    cur = con.execute(f"INSERT INTO saida ({', '.join(_COLS_SAIDA)}) VALUES ({marc})",
                      _valores_saida(dados))
    return cur.lastrowid


def obter_saida(saida_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM saida WHERE id = ?", (saida_id,)).fetchone()
        return dict(l) if l else None


def obter_grupo_saida(saida_id):
    """Uma saída é editada junto com as "irmãs" da mesma série. Devolve
    {id, serie_id, descricao, categoria_id, forma_pagamento_id, fixo_mensal, lancamentos:[...]}
    onde cada lançamento é {id, data_vencimento, valor, numero_parcela, data_pagamento}."""
    s = obter_saida(saida_id)
    if not s:
        return None
    if s.get("serie_id"):
        with conexao() as con:
            irmas = [dict(l) for l in con.execute(
                "SELECT * FROM saida WHERE serie_id = ? ORDER BY COALESCE(data_vencimento, ''), id",
                (s["serie_id"],)).fetchall()]
    else:
        irmas = [s]
    return {
        "id": saida_id,
        "serie_id": s.get("serie_id"),
        "descricao": s.get("descricao"),
        "categoria_id": s.get("categoria_id"),
        "forma_pagamento_id": s.get("forma_pagamento_id"),
        "fixo_mensal": s.get("fixo_mensal"),
        "lancamentos": [
            {"id": l["id"], "data_vencimento": l["data_vencimento"], "valor": l["valor"],
             "numero_parcela": l["numero_parcela"], "data_pagamento": l["data_pagamento"]}
            for l in irmas
        ],
    }


def salvar_grupo_saida(saida_id, comum, linhas):
    """Grava um grupo de lançamentos de uma vez (novo ou edição).
    `comum`: {descricao, categoria_id, forma_pagamento_id, fixo_mensal} — vale para todos.
    `linhas`: [{id(int|None), data_vencimento, valor, numero_parcela, data_pagamento}].
    Atualiza as linhas com id, insere as sem id, apaga as que sumiram do grupo.
    Devolve o serie_id resultante (None quando sobra 1 lançamento)."""
    linhas = [l for l in linhas
              if any((l.get("data_vencimento"), l.get("valor"),
                      l.get("numero_parcela"), l.get("data_pagamento")))]
    if not linhas:
        return None

    with conexao() as con:
        serie = None
        if saida_id:
            row = con.execute("SELECT serie_id FROM saida WHERE id = ?", (saida_id,)).fetchone()
            serie = row["serie_id"] if row else None
        if len(linhas) == 1:
            serie = None
        elif not serie:
            serie = secrets.token_hex(8)

        # apaga as ocorrências que o usuário removeu da tabela
        enviados = {l["id"] for l in linhas if l.get("id")}
        if saida_id:
            if row and row["serie_id"]:
                antigos = [r["id"] for r in con.execute(
                    "SELECT id FROM saida WHERE serie_id = ?", (row["serie_id"],)).fetchall()]
            else:
                antigos = [saida_id]
            for old in antigos:
                if old not in enviados:
                    con.execute("DELETE FROM saida WHERE id = ?", (old,))

        base = {**comum, "serie_id": serie}
        for l in linhas:
            dados = {**base, "valor": l.get("valor"),
                     "data_vencimento": l.get("data_vencimento"),
                     "data_pagamento": l.get("data_pagamento"),
                     "numero_parcela": l.get("numero_parcela")}
            if l.get("id") and l["id"] in enviados:
                atrib = ", ".join(f"{c} = ?" for c in _COLS_SAIDA)
                con.execute(
                    f"UPDATE saida SET {atrib}, atualizado_em = datetime('now') WHERE id = ?",
                    _valores_saida(dados) + [l["id"]])
            else:
                _inserir_saida(con, dados)
    fazer_backup()
    return serie


def excluir_saida(saida_id):
    with conexao() as con:
        con.execute("DELETE FROM saida WHERE id = ?", (saida_id,))
    fazer_backup()


def marcar_saida_paga(saida_id, paga, data=None):
    d = (data or "").strip() or date.today().isoformat()
    with conexao() as con:
        con.execute("UPDATE saida SET data_pagamento = ?, atualizado_em = datetime('now') WHERE id = ?",
                    (d if paga else None, saida_id))
    fazer_backup()


def _status_saida(s, hoje):
    if s.get("data_pagamento"):
        return "pago"
    d = dias_ate_data(s.get("data_vencimento"))
    if d is None:
        return "a_pagar"
    return "vencido" if d < 0 else "a_pagar"


def listar_saidas(mes=None, status=None, categoria_id=None, busca=None,
                  forma_pagamento_id=None, fixo=None,
                  data_ini=None, data_fim=None, base_data="vencimento"):
    """`data_ini`/`data_fim` (ISO, inclusivo) recortam por `base_data`:
    'vencimento' → `data_vencimento`; 'pagamento' → `data_pagamento` (exclui não pagas)."""
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT s.id, s.descricao, s.categoria_id, s.forma_pagamento_id, s.valor, "
            "       s.data_vencimento, s.data_pagamento, s.numero_parcela, s.fixo_mensal, "
            "       s.serie_id, s.criado_em, s.atualizado_em, "
            "       c.nome AS categoria, fp.nome AS forma_pagamento "
            "FROM saida s "
            "LEFT JOIN categoria_saida c ON c.id = s.categoria_id "
            "LEFT JOIN forma_pagamento fp ON fp.id = s.forma_pagamento_id "
            "ORDER BY COALESCE(s.data_vencimento, ''), s.id"
        ).fetchall()]
    hoje = date.today().isoformat()
    for s in linhas:
        s["status"] = _status_saida(s, hoje)
        s["dias_restantes"] = dias_ate_data(s.get("data_vencimento"))

    if mes:
        linhas = [s for s in linhas if (s.get("data_vencimento") or "")[5:7] == f"{int(mes):02d}"]

    if base_data == "pagamento":
        # só pagas, recortadas pela data do pagamento
        linhas = [s for s in linhas if s.get("data_pagamento")]
        campos_periodo = ("data_pagamento",)
    elif base_data == "vencimento":
        campos_periodo = ("data_vencimento",)
    else:
        # nenhum escolhido → casa se o vencimento OU o pagamento cai no intervalo
        campos_periodo = ("data_vencimento", "data_pagamento")

    def _no_intervalo(s):
        for campo in campos_periodo:
            d = s.get(campo) or ""
            if d and (not data_ini or d >= data_ini) and (not data_fim or d <= data_fim):
                return True
        return False

    if data_ini or data_fim:
        linhas = [s for s in linhas if _no_intervalo(s)]
    if status in ("pago", "a_pagar", "vencido"):
        linhas = [s for s in linhas if s["status"] == status]
    if categoria_id:
        linhas = [s for s in linhas if s.get("categoria_id") == int(categoria_id)]
    if forma_pagamento_id:
        linhas = [s for s in linhas if s.get("forma_pagamento_id") == int(forma_pagamento_id)]
    if fixo in ("0", "1", 0, 1):
        alvo_fixo = int(fixo)
        linhas = [s for s in linhas if (1 if s.get("fixo_mensal") else 0) == alvo_fixo]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [s for s in linhas if alvo in _sem_acento_minusculo(s.get("descricao") or "")]
    return linhas


def categorias_saida():
    """Lista o cadastro de categorias de saída ([{id, nome}])."""
    return listar_simples("categoria_saida")


def descricoes_saida():
    """Descrições distintas já cadastradas em `saida` (p/ o autocomplete da busca)."""
    with conexao() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT descricao FROM saida "
            "WHERE descricao IS NOT NULL AND TRIM(descricao) <> '' "
            "ORDER BY descricao COLLATE NOCASE"
        ).fetchall()]


def saidas_a_pagar(limite_dias):
    """Saídas não pagas vencendo em <= limite_dias (inclui as já vencidas), mais urgente 1º."""
    itens = []
    for s in listar_saidas(status=None):
        if s["status"] == "pago":
            continue
        d = s["dias_restantes"]
        if d is not None and d <= limite_dias:
            itens.append(s)
    itens.sort(key=lambda x: (x["dias_restantes"] is None, x["dias_restantes"]))
    return itens


def resumo_saidas():
    with conexao() as con:
        mes = date.today().strftime("%Y-%m")
        a_pagar_mes = con.execute(
            "SELECT COALESCE(SUM(valor), 0) FROM saida "
            "WHERE data_pagamento IS NULL AND substr(data_vencimento, 1, 7) = ?", (mes,)
        ).fetchone()[0]
        vencido = con.execute(
            "SELECT COALESCE(SUM(valor), 0) FROM saida "
            "WHERE data_pagamento IS NULL AND data_vencimento < ?", (date.today().isoformat(),)
        ).fetchone()[0]
    return {"a_pagar_mes": a_pagar_mes, "vencido": vencido}
