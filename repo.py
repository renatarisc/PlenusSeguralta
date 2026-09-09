"""Consultas ao banco, por entidade. Cresce junto com o sistema.

Cada função abre sua própria conexão (via db.conexao) e devolve dicts / listas de dicts.
"""

import secrets
import unicodedata
from datetime import date

from db import conexao, fazer_backup, _um
from validacao import so_digitos, para_decimal, dias_ate_data
from seguranca import hash_senha, senha_confere


# ---------- usuários (login) ----------

_COLS_USUARIO_PUB = "id, nome, login, ativo, criado_em, ultimo_acesso"


def contar_usuarios():
    with conexao() as con:
        return _um(con.execute("SELECT COUNT(*) FROM usuario"))


def listar_usuarios():
    with conexao() as con:
        return [dict(l) for l in con.execute(
            f"SELECT {_COLS_USUARIO_PUB} FROM usuario ORDER BY nome"
        ).fetchall()]


def obter_usuario(uid):
    with conexao() as con:
        l = con.execute(f"SELECT {_COLS_USUARIO_PUB} FROM usuario WHERE id = %s", (uid,)).fetchone()
        return dict(l) if l else None


def autenticar(login, senha):
    """Devolve {id, nome, login} se ok e ativo; senão None. Marca ultimo_acesso."""
    login = (login or "").strip()
    with conexao() as con:
        u = con.execute("SELECT * FROM usuario WHERE login = %s", (login,)).fetchone()
        if not u or not u["ativo"] or not senha_confere(senha, u["senha_hash"]):
            return None
        con.execute("UPDATE usuario SET ultimo_acesso = NOW() WHERE id = %s", (u["id"],))
    return {"id": u["id"], "nome": u["nome"], "login": u["login"]}


def login_em_uso(login, ignorar_id=None):
    with conexao() as con:
        r = con.execute(
            "SELECT id FROM usuario WHERE login = %s AND NOT (id <=> %s)",
            ((login or "").strip(), ignorar_id),
        ).fetchone()
        return r is not None


def criar_usuario(nome, login, senha):
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO usuario (nome, login, senha_hash) VALUES (%s, %s, %s)",
            ((nome or "").strip(), (login or "").strip(), hash_senha(senha)),
        )
        novo = cur.lastrowid
    fazer_backup()
    return novo


def atualizar_usuario(uid, nome, login, ativo, senha=None):
    campos = "nome = %s, login = %s, ativo = %s"
    valores = [(nome or "").strip(), (login or "").strip(), 1 if ativo else 0]
    if senha:
        campos += ", senha_hash = %s"
        valores.append(hash_senha(senha))
    valores.append(uid)
    with conexao() as con:
        con.execute(f"UPDATE usuario SET {campos} WHERE id = %s", valores)
    fazer_backup()


def excluir_usuario(uid):
    with conexao() as con:
        con.execute("DELETE FROM usuario WHERE id = %s", (uid,))
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
    "nome", "tipo_pessoa", "data_nascimento", "sexo", "cpf",
    "end_rua", "end_numero", "end_complemento", "end_bairro", "end_cep", "end_cidade", "end_estado",
    "tel_ddd", "tel_numero", "email",
)


def _valores_cliente(dados):
    valores = []
    for col in _COLS_CLIENTE:
        v = (dados.get(col) or "").strip()
        if col == "tipo_pessoa":
            valores.append("J" if v.upper() == "J" else "F")  # NOT NULL: sempre F ou J
            continue
        if col in ("cpf", "end_cep", "tel_ddd", "tel_numero"):
            v = so_digitos(v)
        valores.append(v or None)
    return valores


def listar_clientes(busca=None, uf=None, cidade=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT id, nome, tipo_pessoa, cpf, end_cidade, end_estado, tel_ddd, tel_numero, email "
            "FROM cliente ORDER BY nome"
        ).fetchall()]

    if uf:
        linhas = [c for c in linhas if (c["end_estado"] or "") == uf]
    if cidade:
        linhas = [c for c in linhas if (c["end_cidade"] or "") == cidade]

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


def tipos_seguro_por_cliente():
    """{cliente_id: [nomes de tipo de seguro das apólices do cliente]} — p/ agrupar
    a lista de clientes por tipo de seguro (cliente com vários tipos entra em vários)."""
    with conexao() as con:
        rows = con.execute(
            "SELECT DISTINCT a.cliente_id, t.nome "
            "  FROM apolice a "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            " WHERE a.cliente_id IS NOT NULL"
        ).fetchall()
    m = {}
    for cid, nome in rows:
        m.setdefault(cid, set()).add(nome or "(sem tipo)")
    return {k: sorted(v, key=_sem_acento_minusculo) for k, v in m.items()}


def clientes_com_consorcio():
    """Conjunto de cliente_id que têm ao menos um consórcio."""
    with conexao() as con:
        return {r["cliente_id"] for r in con.execute(
            "SELECT DISTINCT cliente_id FROM consorcio WHERE cliente_id IS NOT NULL"
        ).fetchall()}


def ufs_dos_clientes():
    with conexao() as con:
        return [r["end_estado"] for r in con.execute(
            "SELECT DISTINCT end_estado FROM cliente "
            "WHERE end_estado IS NOT NULL AND end_estado <> '' ORDER BY end_estado"
        ).fetchall()]


def cidades_dos_clientes(uf=None):
    sql = ("SELECT DISTINCT end_cidade FROM cliente "
           "WHERE end_cidade IS NOT NULL AND end_cidade <> ''")
    params = []
    if uf:
        sql += " AND end_estado = %s"
        params.append(uf)
    sql += " ORDER BY end_cidade"
    with conexao() as con:
        return [r["end_cidade"] for r in con.execute(sql, params).fetchall()]


def obter_cliente(cliente_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM cliente WHERE id = %s", (cliente_id,)).fetchone()
        return dict(l) if l else None


def cliente_por_documento(doc, ignorar_id=None):
    """Cliente que já tem esse CPF/CNPJ -> {id, nome}, ou None. Compara só por dígitos.
    Documento vazio nunca casa."""
    digitos = so_digitos(doc)
    if not digitos:
        return None
    sql = "SELECT id, nome FROM cliente WHERE cpf = %s"
    params = [digitos]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    with conexao() as con:
        l = con.execute(sql, params).fetchone()
        return dict(l) if l else None


def criar_cliente(dados):
    with conexao() as con:
        marc = ", ".join("%s" for _ in _COLS_CLIENTE)
        cur = con.execute(
            f"INSERT INTO cliente ({', '.join(_COLS_CLIENTE)}) VALUES ({marc})",
            _valores_cliente(dados),
        )
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def atualizar_cliente(cliente_id, dados):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_CLIENTE)
        con.execute(
            f"UPDATE cliente SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_cliente(dados) + [cliente_id],
        )
    fazer_backup()


def excluir_cliente(cliente_id):
    with conexao() as con:
        con.execute("DELETE FROM cliente WHERE id = %s", (cliente_id,))
    fazer_backup()


# ---------- cadastros simples (tipo_seguro, forma_pagamento) - só nome ----------

_TABELAS_SIMPLES = {"tipo_seguro", "forma_pagamento", "seguradora", "categoria_saida", "tipo_consorcio"}


def listar_simples(tabela, busca=None):
    assert tabela in _TABELAS_SIMPLES
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            f"SELECT id, nome FROM {tabela} ORDER BY nome"
        ).fetchall()]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [l for l in linhas if alvo in _sem_acento_minusculo(l["nome"])]
    return linhas


def obter_simples(tabela, item_id):
    assert tabela in _TABELAS_SIMPLES
    with conexao() as con:
        l = con.execute(f"SELECT id, nome FROM {tabela} WHERE id = %s", (item_id,)).fetchone()
        return dict(l) if l else None


def nome_simples_existe(tabela, nome, ignorar_id=None):
    """True se já há um registro com esse nome (sem diferenciar maiúsc./acentuação de caixa)."""
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome:
        return False
    sql = f"SELECT 1 FROM {tabela} WHERE nome = %s"
    params = [nome]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    with conexao() as con:
        return con.execute(sql, params).fetchone() is not None


def criar_simples(tabela, nome):
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome or nome_simples_existe(tabela, nome):
        return None
    with conexao() as con:
        cur = con.execute(f"INSERT INTO {tabela} (nome) VALUES (%s)", (nome,))
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def renomear_simples(tabela, item_id, nome):
    assert tabela in _TABELAS_SIMPLES
    nome = (nome or "").strip()
    if not nome or nome_simples_existe(tabela, nome, ignorar_id=item_id):
        return False
    with conexao() as con:
        con.execute(f"UPDATE {tabela} SET nome = %s WHERE id = %s", (nome, item_id))
    fazer_backup()
    return True


def excluir_simples(tabela, item_id):
    assert tabela in _TABELAS_SIMPLES
    with conexao() as con:
        con.execute(f"DELETE FROM {tabela} WHERE id = %s", (item_id,))
    fazer_backup()


# ---------- cotação: campos configuráveis (nome + tipo) ----------

# papéis que um campo pode assumir no cálculo do PDF de cotação (só um dono por papel)
PAPEIS_CAMPO_COTACAO = ("base_parcelamento", "num_parcelas")


def listar_campos_cotacao(busca=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT id, nome, tipo, ordem, papel, opcoes FROM cotacao_campo "
            "ORDER BY ordem, nome"
        ).fetchall()]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [l for l in linhas if alvo in _sem_acento_minusculo(l["nome"])]
    return linhas


def obter_campo_cotacao(campo_id):
    with conexao() as con:
        l = con.execute("SELECT id, nome, tipo, ordem, papel, opcoes FROM cotacao_campo WHERE id = %s",
                        (campo_id,)).fetchone()
        return dict(l) if l else None


def _aplicar_papel(con, campo_id, papel):
    """Garante um único dono por papel: tira o papel de quem tinha e põe neste campo
    (ou limpa, se papel vazio)."""
    papel = (papel or "").strip()
    if papel not in PAPEIS_CAMPO_COTACAO:
        con.execute("UPDATE cotacao_campo SET papel = '' WHERE id = %s", (campo_id,))
        return
    con.execute("UPDATE cotacao_campo SET papel = '' WHERE papel = %s AND id <> %s", (papel, campo_id))
    con.execute("UPDATE cotacao_campo SET papel = %s WHERE id = %s", (papel, campo_id))


def campo_cotacao_nome_existe(nome, ignorar_id=None):
    nome = (nome or "").strip()
    if not nome:
        return False
    sql = "SELECT 1 FROM cotacao_campo WHERE nome = %s"
    params = [nome]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    with conexao() as con:
        return con.execute(sql, params).fetchone() is not None


def campo_cotacao_ordem_existe(ordem, ignorar_id=None):
    try:
        ordem = int(ordem)
    except (TypeError, ValueError):
        return False
    sql = "SELECT 1 FROM cotacao_campo WHERE ordem = %s"
    params = [ordem]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    with conexao() as con:
        return con.execute(sql, params).fetchone() is not None


def criar_campo_cotacao(nome, tipo, ordem=None, papel="", opcoes=""):
    with conexao() as con:
        if ordem is None:
            ordem = _um(con.execute("SELECT COALESCE(MAX(ordem), 0) + 1 FROM cotacao_campo"))
        cur = con.execute(
            "INSERT INTO cotacao_campo (nome, tipo, ordem, opcoes) VALUES (%s, %s, %s, %s)",
            ((nome or "").strip(), (tipo or "").strip(), int(ordem), (opcoes or "").strip()))
        novo_id = cur.lastrowid
        _aplicar_papel(con, novo_id, papel)
    fazer_backup()
    return novo_id


def atualizar_campo_cotacao(campo_id, nome, tipo, ordem=None, papel=None, opcoes=None):
    sets = ["nome = %s", "tipo = %s"]
    vals = [(nome or "").strip(), (tipo or "").strip()]
    if ordem is not None:
        sets.append("ordem = %s")
        vals.append(int(ordem))
    if opcoes is not None:
        sets.append("opcoes = %s")
        vals.append((opcoes or "").strip())
    vals.append(campo_id)
    with conexao() as con:
        con.execute(f"UPDATE cotacao_campo SET {', '.join(sets)} WHERE id = %s", vals)
        if papel is not None:
            _aplicar_papel(con, campo_id, papel)
    fazer_backup()


def atualizar_campo_cotacao_ordem(campo_id, ordem):
    with conexao() as con:
        con.execute("UPDATE cotacao_campo SET ordem = %s WHERE id = %s", (int(ordem), campo_id))
    fazer_backup()


def excluir_campo_cotacao(campo_id):
    with conexao() as con:
        con.execute("DELETE FROM cotacao_campo WHERE id = %s", (campo_id,))
    fazer_backup()


# ---------- apólice (+ parcelas) ----------

_COLS_APOLICE = (
    "cliente_id", "seguradora_id", "tipo_seguro_id", "numero_apolice",
    "vigencia_inicio", "vigencia_fim",
    "premio_liquido", "iof", "premio_total",
    "forma_pagamento_id", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
    "comissao_parcelada", "comissao_cocorretagem",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive",
    "veiculo_placa", "veiculo_descricao",
    "aviso_vigencia_ok", "aviso_vigencia_ok_em",
    "apolice_enviada", "apolice_enviada_data", "cartao_enviado", "cartao_enviado_data",
    "observacao",
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
        (dados.get("data_seguralta_recebido") or "").strip() or None,
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
        (dados.get("observacao") or "").strip() or None,
    ]


def _inserir_parcelas(con, apolice_id, parcelas):
    hoje = date.today().isoformat()
    for p in parcelas or []:
        paga = 1 if p.get("paga") in (1, "1", True, "sim", "on") else 0
        pago_em = (p.get("pago_em") or "").strip() or (hoje if paga else None)
        aviso = 1 if p.get("aviso_ok") in (1, "1", True, "sim", "on") else 0
        aviso_em = (p.get("aviso_ok_em") or "").strip() or (hoje if aviso else None)
        enviado = 1 if p.get("enviado") in (1, "1", True, "sim", "on") else 0
        enviado_em = (p.get("enviado_em") or "").strip() or (hoje if enviado else None)
        con.execute(
            "INSERT INTO apolice_parcela "
            "(apolice_id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em, "
            " enviado, enviado_em) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (apolice_id, p.get("identificacao"), p.get("data"), p.get("valor"),
             paga, pago_em, aviso, aviso_em, enviado, enviado_em),
        )


def _inserir_comissoes(con, apolice_id, linhas):
    for i, c in enumerate(linhas or []):
        con.execute(
            "INSERT INTO apolice_comissao "
            "(apolice_id, parcela, valor_previsto, valor_recebido, data, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (apolice_id, c.get("parcela"), c.get("valor_previsto"),
             c.get("valor_recebido"), c.get("data"), i),
        )


def _inserir_repasses(con, apolice_id, linhas):
    for i, r in enumerate(linhas or []):
        conf = 1 if r.get("conferido_banco") in (1, "1", True, "sim", "on") else 0
        con.execute(
            "INSERT INTO apolice_repasse "
            "(apolice_id, parcela, valor_previsto, valor_recebido, data, conferido_banco, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (apolice_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), conf, i),
        )


def listar_apolices(cliente_id=None, tipo_seguro_id=None, mes_inicio=None, quiver=None,
                    busca=None, parcela_status=None, mes_fim=None, ordem=None,
                    forma_pagamento_id=None):
    sql = """SELECT a.id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
                    a.premio_liquido, a.lancado_quiver, a.aviso_vigencia_ok, a.cliente_id,
                    c.nome AS cliente_nome, c.tipo_pessoa AS cliente_tipo_pessoa,
                    t.nome AS tipo_seguro_nome,
                    s.nome AS seguradora_nome,
                    (SELECT p.data FROM apolice_parcela p
                       WHERE p.apolice_id = a.id AND COALESCE(p.paga, 0) = 0 AND p.data IS NOT NULL
                       ORDER BY p.data LIMIT 1) AS proxima_parcela_data,
                    (SELECT p.valor FROM apolice_parcela p
                       WHERE p.apolice_id = a.id AND COALESCE(p.paga, 0) = 0 AND p.data IS NOT NULL
                       ORDER BY p.data LIMIT 1) AS proxima_parcela_valor,
                    (SELECT COUNT(*) FROM apolice_parcela p WHERE p.apolice_id = a.id) AS total_parcelas,
                    (SELECT COUNT(*) FROM apolice_endosso e WHERE e.apolice_id = a.id) AS qtd_endossos
               FROM apolice a
               LEFT JOIN cliente c     ON c.id = a.cliente_id
               LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id
               LEFT JOIN seguradora s  ON s.id = a.seguradora_id"""
    filtros, params = [], []
    if cliente_id:
        filtros.append("a.cliente_id = %s")
        params.append(cliente_id)
    if tipo_seguro_id:
        filtros.append("a.tipo_seguro_id = %s")
        params.append(tipo_seguro_id)
    if forma_pagamento_id:
        filtros.append("a.forma_pagamento_id = %s")
        params.append(forma_pagamento_id)
    if mes_inicio:
        filtros.append("substr(a.vigencia_inicio, 6, 2) = %s")
        params.append(f"{int(mes_inicio):02d}")
    if mes_fim:
        filtros.append("substr(a.vigencia_fim, 6, 2) = %s")
        params.append(f"{int(mes_fim):02d}")
    if quiver in (0, 1, True, False):
        filtros.append("COALESCE(a.lancado_quiver, 0) = %s")
        params.append(1 if quiver in (1, True) else 0)
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    if ordem == "cliente":
        sql += " ORDER BY c.nome, a.criado_em DESC, a.id DESC"
    elif ordem == "cliente_desc":
        sql += " ORDER BY c.nome DESC, a.criado_em DESC, a.id DESC"
    else:
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
        return _um(con.execute("SELECT COUNT(*) FROM apolice WHERE cliente_id = %s", (cliente_id,)))


# ---------- números do painel ----------

def resumo_painel():
    with conexao() as con:
        um = lambda sql: _um(con.execute(sql))
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
            " ORDER BY qtd DESC, nome"
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
        return _um(con.execute(
            "SELECT COUNT(*) FROM apolice "
            "WHERE vigencia_fim IS NOT NULL AND vigencia_fim <> '' "
            "  AND vigencia_fim <= (CURDATE() + INTERVAL %s DAY)",
            (int(limite_dias),),
        ))


def obter_apolice(apolice_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM apolice WHERE id = %s", (apolice_id,)).fetchone()
        if not l:
            return None
        ap = dict(l)
        ap["parcelas"] = [dict(p) for p in con.execute(
            "SELECT id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em, "
            "       enviado, enviado_em "
            "FROM apolice_parcela WHERE apolice_id = %s ORDER BY COALESCE(data, ''), id",
            (apolice_id,),
        ).fetchall()]
        ap["comissoes"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data "
            "FROM apolice_comissao WHERE apolice_id = %s ORDER BY ordem, id",
            (apolice_id,),
        ).fetchall()]
        ap["repasses"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data, conferido_banco "
            "FROM apolice_repasse WHERE apolice_id = %s ORDER BY ordem, id",
            (apolice_id,),
        ).fetchall()]
        return ap


def _tabela_parcela(origem):
    return {"endosso": "apolice_endosso_parcela",
            "consorcio": "consorcio_boleto"}.get(origem, "apolice_parcela")


def marcar_parcela_paga(parcela_id, paga, origem="apolice"):
    hoje = date.today().isoformat() if paga else None
    with conexao() as con:
        if origem == "consorcio":
            con.execute(
                "UPDATE consorcio_boleto SET status = %s, data_pagamento = %s WHERE id = %s",
                ("pago" if paga else "enviado", hoje, parcela_id))
        else:
            con.execute(
                f"UPDATE {_tabela_parcela(origem)} SET paga = %s, pago_em = %s WHERE id = %s",
                (1 if paga else 0, hoje, parcela_id))
    fazer_backup()


def marcar_aviso_parcela(parcela_id, ok, origem="apolice"):
    with conexao() as con:
        con.execute(
            f"UPDATE {_tabela_parcela(origem)} SET aviso_ok = %s, aviso_ok_em = %s WHERE id = %s",
            (1 if ok else 0, date.today().isoformat() if ok else None, parcela_id),
        )
    fazer_backup()


def marcar_aviso_vigencia(apolice_id, ok):
    with conexao() as con:
        con.execute(
            "UPDATE apolice SET aviso_vigencia_ok = %s, aviso_vigencia_ok_em = %s WHERE id = %s",
            (1 if ok else 0, date.today().isoformat() if ok else None, apolice_id),
        )
    fazer_backup()


def criar_apolice(dados, parcelas, comissoes=None, repasses=None):
    with conexao() as con:
        marcadores = ", ".join("%s" for _ in _COLS_APOLICE)
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
        atrib = ", ".join(f"{c} = %s" for c in _COLS_APOLICE)
        con.execute(
            f"UPDATE apolice SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_apolice(dados) + [apolice_id],
        )
        con.execute("DELETE FROM apolice_parcela WHERE apolice_id = %s", (apolice_id,))
        _inserir_parcelas(con, apolice_id, parcelas)
        con.execute("DELETE FROM apolice_comissao WHERE apolice_id = %s", (apolice_id,))
        _inserir_comissoes(con, apolice_id, comissoes)
        con.execute("DELETE FROM apolice_repasse WHERE apolice_id = %s", (apolice_id,))
        _inserir_repasses(con, apolice_id, repasses)
    fazer_backup()


def excluir_apolice(apolice_id):
    with conexao() as con:
        con.execute("DELETE FROM apolice WHERE id = %s", (apolice_id,))
    fazer_backup()


# ---------- endossos ----------

_SITUACOES_ENDOSSO = ("onus", "devolucao", "sem_alteracao")

_COLS_ENDOSSO = (
    "apolice_id", "numero", "vigencia_inicio", "vigencia_fim", "motivacao",
    "situacao", "valor", "forma_pagamento_id", "veiculo_placa", "veiculo_descricao",
    "comissao_parcelada", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
    "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive",
)


def _valores_endosso(d):
    return [
        _int_ou_none(d.get("apolice_id")),
        (d.get("numero") or "").strip() or None,
        (d.get("vigencia_inicio") or "").strip() or None,
        (d.get("vigencia_fim") or "").strip() or None,
        (d.get("motivacao") or "").strip() or None,
        d.get("situacao") if d.get("situacao") in _SITUACOES_ENDOSSO else "sem_alteracao",
        para_decimal(d.get("valor")),
        _int_ou_none(d.get("forma_pagamento_id")),
        (d.get("veiculo_placa") or "").strip().upper() or None,
        (d.get("veiculo_descricao") or "").strip() or None,
        _sim_nao(d.get("comissao_parcelada")),
        para_decimal(d.get("comissao_percentual")),
        para_decimal(d.get("comissao_valor_seguralta_receber")),
        para_decimal(d.get("comissao_valor_seguralta_recebido")),
        para_decimal(d.get("comissao_valor_plenus_receber")),
        para_decimal(d.get("comissao_valor_plenus_recebido")),
        (d.get("data_seguralta_recebido") or "").strip() or None,
        (d.get("data_plenus_recebido") or "").strip() or None,
        _sim_nao(d.get("plenus_conferido_banco")),
        para_decimal(d.get("previsto_relatorio_seguralta")),
        para_decimal(d.get("recebido_relatorio_seguralta")),
        para_decimal(d.get("previsto_relatorio_plenus")),
        para_decimal(d.get("recebido_relatorio_plenus")),
        _sim_nao(d.get("lancado_quiver")),
        (d.get("link_onedrive") or "").strip() or None,
    ]


def _inserir_endosso_comissoes(con, endosso_id, linhas):
    for i, c in enumerate(linhas or []):
        con.execute(
            "INSERT INTO apolice_endosso_comissao "
            "(endosso_id, parcela, valor_previsto, valor_recebido, data, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (endosso_id, c.get("parcela"), c.get("valor_previsto"),
             c.get("valor_recebido"), c.get("data"), i))


def _inserir_endosso_repasses(con, endosso_id, linhas):
    for i, r in enumerate(linhas or []):
        conf = 1 if r.get("conferido_banco") in (1, "1", True, "sim", "on") else 0
        con.execute(
            "INSERT INTO apolice_endosso_repasse "
            "(endosso_id, parcela, valor_previsto, valor_recebido, data, conferido_banco, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (endosso_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), conf, i))


def _inserir_endosso_parcelas(con, endosso_id, parcelas):
    hoje = date.today().isoformat()
    for p in parcelas or []:
        paga = 1 if p.get("paga") in (1, "1", True, "sim", "on") else 0
        pago_em = (p.get("pago_em") or "").strip() or (hoje if paga else None)
        aviso = 1 if p.get("aviso_ok") in (1, "1", True, "sim", "on") else 0
        aviso_em = (p.get("aviso_ok_em") or "").strip() or (hoje if aviso else None)
        enviado = 1 if p.get("enviado") in (1, "1", True, "sim", "on") else 0
        enviado_em = (p.get("enviado_em") or "").strip() or (hoje if enviado else None)
        con.execute(
            "INSERT INTO apolice_endosso_parcela "
            "(endosso_id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em, "
            " enviado, enviado_em) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (endosso_id, p.get("identificacao"), p.get("data"), p.get("valor"),
             paga, pago_em, aviso, aviso_em, enviado, enviado_em),
        )


_SQL_ENDOSSO_SEL = """
SELECT e.*, a.numero_apolice, a.cliente_id,
       c.nome AS cliente_nome, c.tipo_pessoa AS cliente_tipo_pessoa, s.nome AS seguradora_nome,
       t.nome AS tipo_seguro_nome, f.nome AS forma_pagamento_nome,
       (SELECT p.data FROM apolice_endosso_parcela p
          WHERE p.endosso_id = e.id AND COALESCE(p.paga, 0) = 0 AND p.data IS NOT NULL
          ORDER BY p.data LIMIT 1) AS proxima_parcela_data,
       (SELECT COUNT(*) FROM apolice_endosso_parcela p WHERE p.endosso_id = e.id) AS total_parcelas
  FROM apolice_endosso e
  JOIN apolice a          ON a.id = e.apolice_id
  LEFT JOIN cliente c     ON c.id = a.cliente_id
  LEFT JOIN seguradora s  ON s.id = a.seguradora_id
  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id
  LEFT JOIN forma_pagamento f ON f.id = e.forma_pagamento_id
"""


def listar_endossos(apolice_id=None, busca=None):
    sql, params = _SQL_ENDOSSO_SEL, []
    if apolice_id:
        sql += " WHERE e.apolice_id = %s"
        params.append(apolice_id)
    sql += " ORDER BY e.criado_em DESC, e.id DESC"
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(sql, params).fetchall()]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [l for l in linhas
                  if alvo in _sem_acento_minusculo(l.get("cliente_nome") or "")
                  or alvo in _sem_acento_minusculo(l.get("numero_apolice") or "")
                  or alvo in _sem_acento_minusculo(l.get("numero") or "")]
    return linhas


def obter_endosso(endosso_id):
    with conexao() as con:
        l = con.execute(_SQL_ENDOSSO_SEL + " WHERE e.id = %s", (endosso_id,)).fetchone()
        if not l:
            return None
        e = dict(l)
        e["parcelas"] = [dict(p) for p in con.execute(
            "SELECT id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em, "
            "       enviado, enviado_em "
            "FROM apolice_endosso_parcela WHERE endosso_id = %s ORDER BY COALESCE(data, ''), id",
            (endosso_id,)).fetchall()]
        e["comissoes"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data "
            "FROM apolice_endosso_comissao WHERE endosso_id = %s ORDER BY ordem, id",
            (endosso_id,)).fetchall()]
        e["repasses"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data, conferido_banco "
            "FROM apolice_endosso_repasse WHERE endosso_id = %s ORDER BY ordem, id",
            (endosso_id,)).fetchall()]
        return e


def criar_endosso(dados, parcelas=None, comissoes=None, repasses=None):
    with conexao() as con:
        marc = ", ".join("%s" for _ in _COLS_ENDOSSO)
        cur = con.execute(
            f"INSERT INTO apolice_endosso ({', '.join(_COLS_ENDOSSO)}) VALUES ({marc})",
            _valores_endosso(dados))
        novo_id = cur.lastrowid
        _inserir_endosso_parcelas(con, novo_id, parcelas)
        _inserir_endosso_comissoes(con, novo_id, comissoes)
        _inserir_endosso_repasses(con, novo_id, repasses)
    fazer_backup()
    return novo_id


def atualizar_endosso(endosso_id, dados, parcelas=None, comissoes=None, repasses=None):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_ENDOSSO)
        con.execute(
            f"UPDATE apolice_endosso SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_endosso(dados) + [endosso_id])
        for tab in ("apolice_endosso_parcela", "apolice_endosso_comissao", "apolice_endosso_repasse"):
            con.execute(f"DELETE FROM {tab} WHERE endosso_id = %s", (endosso_id,))
        _inserir_endosso_parcelas(con, endosso_id, parcelas)
        _inserir_endosso_comissoes(con, endosso_id, comissoes)
        _inserir_endosso_repasses(con, endosso_id, repasses)
    fazer_backup()


def excluir_endosso(endosso_id):
    with conexao() as con:
        con.execute("DELETE FROM apolice_endosso WHERE id = %s", (endosso_id,))
    fazer_backup()


def contar_endossos_por_apolice(apolice_id):
    with conexao() as con:
        return _um(con.execute("SELECT COUNT(*) FROM apolice_endosso WHERE apolice_id = %s",
                               (apolice_id,)))


# ---------- consórcios ----------

_SITUACOES_CONSORCIO = ("ativo", "contemplado", "quitado", "cancelado", "desistente")
_CONTEMPLACOES_CONSORCIO = ("sorteio", "lance")

_COLS_CONSORCIO = (
    "cliente_id", "seguradora_id", "tipo_consorcio_id", "carta",
    "numero_grupo", "numero_cota", "forma_pagamento_id", "quantidade_parcelas",
    "parcela_dia_vencimento", "situacao", "forma_contemplacao", "data_contemplacao",
    "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
    "comissao_parcelada", "comissao_cocorretagem",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive", "observacao",
)


def _valores_consorcio(d):
    return [
        _int_ou_none(d.get("cliente_id")),
        _int_ou_none(d.get("seguradora_id")),
        _int_ou_none(d.get("tipo_consorcio_id")),
        para_decimal(d.get("carta")),
        (d.get("numero_grupo") or "").strip() or None,
        (d.get("numero_cota") or "").strip() or None,
        _int_ou_none(d.get("forma_pagamento_id")),
        _int_ou_none(d.get("quantidade_parcelas")),
        (d.get("parcela_dia_vencimento") or "").strip() or None,
        d.get("situacao") if d.get("situacao") in _SITUACOES_CONSORCIO else "ativo",
        d.get("forma_contemplacao") if d.get("forma_contemplacao") in _CONTEMPLACOES_CONSORCIO else None,
        (d.get("data_contemplacao") or "").strip() or None,
        para_decimal(d.get("comissao_percentual")),
        para_decimal(d.get("comissao_valor_seguralta_receber")),
        para_decimal(d.get("comissao_valor_plenus_receber")),
        para_decimal(d.get("comissao_valor_seguralta_recebido")),
        para_decimal(d.get("comissao_valor_plenus_recebido")),
        (d.get("data_seguralta_recebido") or "").strip() or None,
        (d.get("data_plenus_recebido") or "").strip() or None,
        _sim_nao(d.get("plenus_conferido_banco")),
        _sim_nao(d.get("comissao_parcelada")),
        _sim_nao(d.get("comissao_cocorretagem")),
        para_decimal(d.get("previsto_relatorio_seguralta")),
        para_decimal(d.get("recebido_relatorio_seguralta")),
        para_decimal(d.get("previsto_relatorio_plenus")),
        para_decimal(d.get("recebido_relatorio_plenus")),
        _sim_nao(d.get("lancado_quiver")),
        (d.get("link_onedrive") or "").strip() or None,
        (d.get("observacao") or "").strip() or None,
    ]


def _inserir_consorcio_parcela_valores(con, consorcio_id, linhas):
    for i, v in enumerate(linhas or []):
        con.execute(
            "INSERT INTO consorcio_parcela_valor (consorcio_id, valor, data, ordem) "
            "VALUES (%s, %s, %s, %s)",
            (consorcio_id, v.get("valor"), v.get("data"), i))


def _inserir_consorcio_comissoes(con, consorcio_id, linhas):
    for i, c in enumerate(linhas or []):
        con.execute(
            "INSERT INTO consorcio_comissao "
            "(consorcio_id, parcela, valor_previsto, valor_recebido, data, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (consorcio_id, c.get("parcela"), c.get("valor_previsto"),
             c.get("valor_recebido"), c.get("data"), i))


def _inserir_consorcio_repasses(con, consorcio_id, linhas):
    for i, r in enumerate(linhas or []):
        conf = 1 if r.get("conferido_banco") in (1, "1", True, "sim", "on") else 0
        con.execute(
            "INSERT INTO consorcio_repasse "
            "(consorcio_id, parcela, valor_previsto, valor_recebido, data, conferido_banco, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (consorcio_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), conf, i))


def _inserir_consorcio_boletos(con, consorcio_id, boletos):
    hoje = date.today().isoformat()
    for i, b in enumerate(boletos or []):
        pago_em = (b.get("data_pagamento") or "").strip() or None
        _st = (b.get("status") or "").strip()
        status = "pago" if pago_em else (_st if _st in ("a_enviar", "enviado", "pago") else "a_enviar")
        aviso = 1 if b.get("aviso_ok") in (1, "1", True, "sim", "on") else 0
        aviso_em = (b.get("aviso_ok_em") or "").strip() or (hoje if aviso else None)
        con.execute(
            "INSERT INTO consorcio_boleto "
            "(consorcio_id, identificacao, valor, data_emissao, data_vencimento, "
            " data_pagamento, status, aviso_ok, aviso_ok_em, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (consorcio_id, b.get("identificacao"), b.get("valor"),
             (b.get("data_emissao") or "").strip() or None,
             (b.get("data_vencimento") or "").strip() or None,
             pago_em, status, aviso, aviso_em, i))


_SQL_CONSORCIO_SEL = """
SELECT co.*,
       c.nome AS cliente_nome, c.tipo_pessoa AS cliente_tipo_pessoa, s.nome AS seguradora_nome,
       tc.nome AS tipo_consorcio_nome, f.nome AS forma_pagamento_nome,
       (SELECT b.data_vencimento FROM consorcio_boleto b
          WHERE b.consorcio_id = co.id AND COALESCE(b.status,'') <> 'pago'
                AND b.data_vencimento IS NOT NULL
          ORDER BY b.data_vencimento LIMIT 1) AS proximo_boleto_data,
       (SELECT COUNT(*) FROM consorcio_boleto b WHERE b.consorcio_id = co.id) AS total_boletos,
       (SELECT cv.valor FROM consorcio_parcela_valor cv
          WHERE cv.consorcio_id = co.id ORDER BY cv.ordem DESC, cv.id DESC LIMIT 1) AS parcela_valor_atual
  FROM consorcio co
  LEFT JOIN cliente c        ON c.id = co.cliente_id
  LEFT JOIN seguradora s     ON s.id = co.seguradora_id
  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id
  LEFT JOIN forma_pagamento f ON f.id = co.forma_pagamento_id
"""


def listar_consorcios(busca=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            _SQL_CONSORCIO_SEL + " ORDER BY co.criado_em DESC, co.id DESC").fetchall()]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [l for l in linhas
                  if alvo in _sem_acento_minusculo(l.get("cliente_nome") or "")
                  or alvo in _sem_acento_minusculo(l.get("numero_grupo") or "")
                  or alvo in _sem_acento_minusculo(l.get("numero_cota") or "")
                  or alvo in _sem_acento_minusculo(l.get("tipo_consorcio_nome") or "")]
    return linhas


def obter_consorcio(consorcio_id):
    with conexao() as con:
        l = con.execute(_SQL_CONSORCIO_SEL + " WHERE co.id = %s", (consorcio_id,)).fetchone()
        if not l:
            return None
        co = dict(l)
        co["parcela_valores"] = [dict(x) for x in con.execute(
            "SELECT id, valor, data FROM consorcio_parcela_valor "
            "WHERE consorcio_id = %s ORDER BY ordem, id", (consorcio_id,)).fetchall()]
        co["comissoes"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data "
            "FROM consorcio_comissao WHERE consorcio_id = %s ORDER BY ordem, id",
            (consorcio_id,)).fetchall()]
        co["repasses"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data, conferido_banco "
            "FROM consorcio_repasse WHERE consorcio_id = %s ORDER BY ordem, id",
            (consorcio_id,)).fetchall()]
        co["boletos"] = [dict(x) for x in con.execute(
            "SELECT id, identificacao, valor, data_emissao, data_vencimento, "
            "       data_pagamento, status, aviso_ok, aviso_ok_em "
            "FROM consorcio_boleto WHERE consorcio_id = %s ORDER BY ordem, id",
            (consorcio_id,)).fetchall()]
        return co


def criar_consorcio(dados, parcela_valores=None, comissoes=None, repasses=None, boletos=None):
    with conexao() as con:
        marc = ", ".join("%s" for _ in _COLS_CONSORCIO)
        cur = con.execute(
            f"INSERT INTO consorcio ({', '.join(_COLS_CONSORCIO)}) VALUES ({marc})",
            _valores_consorcio(dados))
        novo_id = cur.lastrowid
        _inserir_consorcio_parcela_valores(con, novo_id, parcela_valores)
        _inserir_consorcio_comissoes(con, novo_id, comissoes)
        _inserir_consorcio_repasses(con, novo_id, repasses)
        _inserir_consorcio_boletos(con, novo_id, boletos)
    fazer_backup()
    return novo_id


def atualizar_consorcio(consorcio_id, dados, parcela_valores=None, comissoes=None,
                        repasses=None, boletos=None):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_CONSORCIO)
        con.execute(
            f"UPDATE consorcio SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_consorcio(dados) + [consorcio_id])
        for tab in ("consorcio_parcela_valor", "consorcio_comissao",
                    "consorcio_repasse", "consorcio_boleto"):
            con.execute(f"DELETE FROM {tab} WHERE consorcio_id = %s", (consorcio_id,))
        _inserir_consorcio_parcela_valores(con, consorcio_id, parcela_valores)
        _inserir_consorcio_comissoes(con, consorcio_id, comissoes)
        _inserir_consorcio_repasses(con, consorcio_id, repasses)
        _inserir_consorcio_boletos(con, consorcio_id, boletos)
    fazer_backup()


def excluir_consorcio(consorcio_id):
    with conexao() as con:
        con.execute("DELETE FROM consorcio WHERE id = %s", (consorcio_id,))
    fazer_backup()


def obter_apolice_basico(apolice_id):
    """id, número, cliente e seguradora — sem carregar parcelas/comissões."""
    with conexao() as con:
        l = con.execute(
            "SELECT a.id, a.numero_apolice, c.nome AS cliente_nome, s.nome AS seguradora_nome "
            "  FROM apolice a "
            "  LEFT JOIN cliente c    ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora s ON s.id = a.seguradora_id "
            " WHERE a.id = %s", (apolice_id,)).fetchone()
        return dict(l) if l else None


def listar_apolices_select():
    """(id, numero_apolice, cliente_nome, tipo_seguro_nome) — leve, p/ o <select> do endosso."""
    with conexao() as con:
        return [dict(l) for l in con.execute(
            "SELECT a.id, a.numero_apolice, c.nome AS cliente_nome, t.nome AS tipo_seguro_nome "
            "  FROM apolice a "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            " ORDER BY c.nome, a.criado_em DESC, a.id DESC").fetchall()]


def salvar_comissoes_repasses(apolice_id, comissoes, repasses):
    """Regrava SÓ as tabelas-filhas de comissão de UMA apólice (mesma lógica
    wipe+reinsert de `atualizar_apolice`), sem tocar em nenhuma coluna da
    `apolice` nem em outras apólices. Usado pela grade editável de Entradas."""
    with conexao() as con:
        con.execute("DELETE FROM apolice_comissao WHERE apolice_id = %s", (apolice_id,))
        _inserir_comissoes(con, apolice_id, comissoes)
        con.execute("DELETE FROM apolice_repasse WHERE apolice_id = %s", (apolice_id,))
        _inserir_repasses(con, apolice_id, repasses)
        con.execute("UPDATE apolice SET atualizado_em = NOW() WHERE id = %s",
                    (apolice_id,))
    fazer_backup()


def salvar_comissao_unica(apolice_id, valores):
    """Grava os valores achatados de comissão (repasse único / cocorretagem) de
    uma apólice. `valores` = dict com as 7 chaves abaixo (float/str ou None)."""
    with conexao() as con:
        con.execute(
            "UPDATE apolice SET "
            "  comissao_valor_seguralta_receber = %s, "
            "  comissao_valor_seguralta_recebido = %s, "
            "  comissao_valor_plenus_receber = %s, "
            "  comissao_valor_plenus_recebido = %s, "
            "  data_seguralta_recebido = %s, "
            "  data_plenus_recebido = %s, "
            "  plenus_conferido_banco = %s, "
            "  atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             1 if valores.get("plenus_conferido_banco") in (1, "1", True, "sim", "on") else 0,
             apolice_id),
        )
    fazer_backup()


def salvar_comissoes_repasses_endosso(endosso_id, comissoes, repasses):
    """Regrava só as tabelas-filhas de comissão parcelada de UM endosso (grade de Entradas)."""
    with conexao() as con:
        con.execute("DELETE FROM apolice_endosso_comissao WHERE endosso_id = %s", (endosso_id,))
        _inserir_endosso_comissoes(con, endosso_id, comissoes)
        con.execute("DELETE FROM apolice_endosso_repasse WHERE endosso_id = %s", (endosso_id,))
        _inserir_endosso_repasses(con, endosso_id, repasses)
        con.execute("UPDATE apolice_endosso SET atualizado_em = NOW() WHERE id = %s", (endosso_id,))
    fazer_backup()


def salvar_comissao_endosso(endosso_id, valores):
    """Grava só a comissão (valores achatados) de um endosso, a partir do bloco
    editável de Entradas. Mesmas 7 chaves de `salvar_comissao_unica`."""
    with conexao() as con:
        con.execute(
            "UPDATE apolice_endosso SET "
            "  comissao_valor_seguralta_receber = %s, comissao_valor_seguralta_recebido = %s, "
            "  comissao_valor_plenus_receber = %s, comissao_valor_plenus_recebido = %s, "
            "  data_seguralta_recebido = %s, data_plenus_recebido = %s, "
            "  plenus_conferido_banco = %s, atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             1 if valores.get("plenus_conferido_banco") in (1, "1", True, "sim", "on") else 0,
             endosso_id),
        )
    fazer_backup()


def salvar_comissoes_repasses_consorcio(consorcio_id, comissoes, repasses):
    """Regrava só as tabelas-filhas de comissão parcelada de UM consórcio (grade de Entradas)."""
    with conexao() as con:
        con.execute("DELETE FROM consorcio_comissao WHERE consorcio_id = %s", (consorcio_id,))
        _inserir_consorcio_comissoes(con, consorcio_id, comissoes)
        con.execute("DELETE FROM consorcio_repasse WHERE consorcio_id = %s", (consorcio_id,))
        _inserir_consorcio_repasses(con, consorcio_id, repasses)
        con.execute("UPDATE consorcio SET atualizado_em = NOW() WHERE id = %s", (consorcio_id,))
    fazer_backup()


def salvar_comissao_consorcio(consorcio_id, valores):
    """Grava só a comissão (valores achatados) de um consórcio, a partir do bloco
    editável de Entradas. Mesmas 7 chaves de `salvar_comissao_unica`."""
    with conexao() as con:
        con.execute(
            "UPDATE consorcio SET "
            "  comissao_valor_seguralta_receber = %s, comissao_valor_seguralta_recebido = %s, "
            "  comissao_valor_plenus_receber = %s, comissao_valor_plenus_recebido = %s, "
            "  data_seguralta_recebido = %s, data_plenus_recebido = %s, "
            "  plenus_conferido_banco = %s, atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             1 if valores.get("plenus_conferido_banco") in (1, "1", True, "sim", "on") else 0,
             consorcio_id),
        )
    fazer_backup()


# ---------- avisos de vencimento (WhatsApp) ----------

def notificacao_ja_enviada(apolice_id, marco, vigencia_fim):
    with conexao() as con:
        r = con.execute(
            "SELECT 1 FROM notificacao_vencimento WHERE apolice_id = %s AND marco = %s AND vigencia_fim <=> %s",
            (apolice_id, marco, vigencia_fim),
        ).fetchone()
        return r is not None


def registrar_notificacao(apolice_id, marco, vigencia_fim, canal, destino, resultado):
    with conexao() as con:
        con.execute(
            """INSERT INTO notificacao_vencimento
                   (apolice_id, marco, vigencia_fim, canal, destino, resultado, enviado_em)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                   canal = VALUES(canal), destino = VALUES(destino),
                   resultado = VALUES(resultado), enviado_em = NOW()""",
            (apolice_id, marco, vigencia_fim, canal, destino, resultado),
        )
    fazer_backup()


# marco 0 = "aviso diário até o cliente ser avisado" (o e-mail usa isto no lugar dos marcos)

def email_vigencia_enviado_hoje(apolice_id):
    with conexao() as con:
        r = con.execute(
            "SELECT 1 FROM notificacao_vencimento "
            "WHERE apolice_id = %s AND marco = 0 AND DATE(enviado_em) = CURDATE()",
            (apolice_id,),
        ).fetchone()
        return r is not None


def _tabela_notif_parcela(origem):
    return {"endosso": "notificacao_endosso_parcela",
            "consorcio": "notificacao_consorcio_boleto"}.get(origem, "notificacao_parcela")


def email_boleto_enviado_hoje(parcela_id, origem="apolice"):
    with conexao() as con:
        r = con.execute(
            f"SELECT 1 FROM {_tabela_notif_parcela(origem)} "
            "WHERE parcela_id = %s AND marco = 0 AND DATE(enviado_em) = CURDATE()",
            (parcela_id,),
        ).fetchone()
        return r is not None


# ---------- avisos de boleto (parcela a vencer) ----------

_SQL_PARCELAS_BOLETO = """
SELECT 'apolice' AS origem, p.id AS parcela_id, NULL AS endosso_id, NULL AS endosso_numero,
       NULL AS consorcio_id, NULL AS consorcio_grupo, NULL AS consorcio_cota, NULL AS boleto_status,
       p.identificacao, p.data, p.valor, p.aviso_ok, p.enviado, p.enviado_em,
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

_SQL_PARCELAS_BOLETO_END = """
SELECT 'endosso' AS origem, p.id AS parcela_id, e.id AS endosso_id, e.numero AS endosso_numero,
       NULL AS consorcio_id, NULL AS consorcio_grupo, NULL AS consorcio_cota, NULL AS boleto_status,
       p.identificacao, p.data, p.valor, p.aviso_ok, p.enviado, p.enviado_em,
       a.id AS apolice_id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
       c.nome AS cliente_nome, s.nome AS seguradora_nome, t.nome AS tipo_seguro_nome,
       f.nome AS forma_pagamento_nome
  FROM apolice_endosso_parcela p
  JOIN apolice_endosso e  ON e.id = p.endosso_id
  JOIN apolice a          ON a.id = e.apolice_id
  LEFT JOIN cliente c     ON c.id = a.cliente_id
  LEFT JOIN seguradora s  ON s.id = a.seguradora_id
  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id
  JOIN forma_pagamento f  ON f.id = e.forma_pagamento_id
 WHERE lower(f.nome) LIKE '%boleto%'
   AND p.data IS NOT NULL AND p.data <> ''
   AND COALESCE(p.paga, 0) = 0
"""

# boletos do consórcio: são boletos por natureza — não filtra pela forma de pagamento
_SQL_PARCELAS_BOLETO_CONS = """
SELECT 'consorcio' AS origem, b.id AS parcela_id, NULL AS endosso_id, NULL AS endosso_numero,
       co.id AS consorcio_id, co.numero_grupo AS consorcio_grupo, co.numero_cota AS consorcio_cota,
       b.status AS boleto_status,
       b.identificacao, b.data_vencimento AS data, b.valor, b.aviso_ok,
       NULL AS apolice_id, NULL AS numero_apolice, NULL AS vigencia_inicio, NULL AS vigencia_fim,
       c.nome AS cliente_nome, s.nome AS seguradora_nome, tc.nome AS tipo_seguro_nome,
       f.nome AS forma_pagamento_nome
  FROM consorcio_boleto b
  JOIN consorcio co        ON co.id = b.consorcio_id
  LEFT JOIN cliente c      ON c.id = co.cliente_id
  LEFT JOIN seguradora s   ON s.id = co.seguradora_id
  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id
  LEFT JOIN forma_pagamento f ON f.id = co.forma_pagamento_id
 WHERE b.data_vencimento IS NOT NULL AND b.data_vencimento <> ''
   AND COALESCE(b.status, '') <> 'pago'
"""


def parcelas_boleto_pendentes():
    """Boletos com data e não pagos — de apólices, endossos E consórcios."""
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO).fetchall()]
        linhas += [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO_END).fetchall()]
        linhas += [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO_CONS).fetchall()]
    linhas.sort(key=lambda l: l.get("data") or "")
    return linhas


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


def boletos_consorcio_a_enviar():
    """Boletos de consórcio já disponíveis para envio: status 'a_enviar' e com
    data de emissão vazia ou já alcançada (não mostra emissões futuras). Mais
    antigo primeiro."""
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT b.id AS boleto_id, b.identificacao, b.valor, "
            "       b.data_emissao, b.data_vencimento, "
            "       co.id AS consorcio_id, co.numero_grupo, co.numero_cota, "
            "       c.nome AS cliente_nome, s.nome AS seguradora_nome, tc.nome AS tipo_consorcio_nome "
            "  FROM consorcio_boleto b "
            "  JOIN consorcio co           ON co.id = b.consorcio_id "
            "  LEFT JOIN cliente c         ON c.id = co.cliente_id "
            "  LEFT JOIN seguradora s      ON s.id = co.seguradora_id "
            "  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id "
            " WHERE COALESCE(b.status, '') = 'a_enviar' "
            "   AND (b.data_emissao IS NULL OR b.data_emissao = '' "
            "        OR b.data_emissao <= CURDATE()) "
            " ORDER BY COALESCE(b.data_emissao, ''), COALESCE(b.data_vencimento, ''), b.id"
        ).fetchall()]
    return linhas


def marcar_boleto_consorcio_enviado(boleto_id, enviado=True):
    """Alterna o status de um boleto de consórcio entre 'enviado' e 'a_enviar'
    (não mexe em boleto já 'pago')."""
    with conexao() as con:
        con.execute(
            "UPDATE consorcio_boleto SET status = %s "
            "WHERE id = %s AND COALESCE(status, '') <> 'pago'",
            ("enviado" if enviado else "a_enviar", boleto_id))
    fazer_backup()


def boletos_a_enviar(limite_dias):
    """Boletos que a corretora ainda precisa repassar ao cliente — de apólices,
    endossos E consórcios — mais antigo primeiro.

    * consórcio: reaproveita `boletos_consorcio_a_enviar()` (status 'a_enviar' + emissão
      já alcançada; sem janela de vencimento);
    * apólice/endosso: parcela de boleto não paga, ainda não enviada, com vencimento
      em <= `limite_dias` dias (inclui as já vencidas)."""
    itens = []
    for b in boletos_consorcio_a_enviar():
        b["origem"] = "consorcio"
        b["parcela_id"] = b["boleto_id"]
        b["data"] = b.get("data_vencimento")
        b["dias_restantes"] = dias_ate_data(b.get("data_vencimento"))
        itens.append(b)
    for p in parcelas_boleto_pendentes():
        if p.get("origem") == "consorcio" or p.get("enviado"):
            continue
        d = dias_ate_data(p.get("data"))
        if d is None or d > limite_dias:
            continue
        p["dias_restantes"] = d
        itens.append(p)
    itens.sort(key=lambda x: x.get("data") or "")
    return itens


def contar_boletos_a_enviar(limite_dias):
    return len(boletos_a_enviar(limite_dias))


def marcar_parcela_enviada(parcela_id, enviado, origem="apolice"):
    """Marca/desmarca uma parcela de boleto como já repassada ao cliente.
    Consórcio usa o `status` do próprio boleto; apólice/endosso usam `enviado`/`enviado_em`."""
    if origem == "consorcio":
        marcar_boleto_consorcio_enviado(parcela_id, enviado)
        return
    with conexao() as con:
        con.execute(
            f"UPDATE {_tabela_parcela(origem)} SET enviado = %s, enviado_em = %s WHERE id = %s",
            (1 if enviado else 0, date.today().isoformat() if enviado else None, parcela_id))
    fazer_backup()


def notificacao_parcela_ja_enviada(parcela_id, marco, data_venc, origem="apolice"):
    with conexao() as con:
        r = con.execute(
            f"SELECT 1 FROM {_tabela_notif_parcela(origem)} "
            "WHERE parcela_id = %s AND marco = %s AND data_vencimento <=> %s",
            (parcela_id, marco, data_venc),
        ).fetchone()
        return r is not None


def registrar_notificacao_parcela(parcela_id, marco, data_venc, canal, destino, resultado, origem="apolice"):
    with conexao() as con:
        con.execute(
            f"""INSERT INTO {_tabela_notif_parcela(origem)}
                   (parcela_id, marco, data_vencimento, canal, destino, resultado, enviado_em)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                   canal = VALUES(canal), destino = VALUES(destino),
                   resultado = VALUES(resultado), enviado_em = NOW()""",
            (parcela_id, marco, data_venc, canal, destino, resultado),
        )
    fazer_backup()


# ---------- eventos do Google Agenda ----------

def evento_agenda_obter(chave):
    with conexao() as con:
        l = con.execute("SELECT * FROM evento_agenda WHERE chave = %s", (chave,)).fetchone()
        return dict(l) if l else None


def evento_agenda_salvar(chave, event_id, data_ref, resumo):
    with conexao() as con:
        con.execute(
            """INSERT INTO evento_agenda (chave, event_id, data_ref, resumo, atualizado_em)
               VALUES (%s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                   event_id = VALUES(event_id), data_ref = VALUES(data_ref),
                   resumo = VALUES(resumo), atualizado_em = NOW()""",
            (chave, event_id, data_ref, resumo),
        )
    fazer_backup()


def evento_agenda_remover(chave):
    with conexao() as con:
        con.execute("DELETE FROM evento_agenda WHERE chave = %s", (chave,))
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
    marc = ", ".join("%s" for _ in _COLS_SAIDA)
    cur = con.execute(f"INSERT INTO saida ({', '.join(_COLS_SAIDA)}) VALUES ({marc})",
                      _valores_saida(dados))
    return cur.lastrowid


def obter_saida(saida_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM saida WHERE id = %s", (saida_id,)).fetchone()
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
                "SELECT * FROM saida WHERE serie_id = %s ORDER BY COALESCE(data_vencimento, ''), id",
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
            row = con.execute("SELECT serie_id FROM saida WHERE id = %s", (saida_id,)).fetchone()
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
                    "SELECT id FROM saida WHERE serie_id = %s", (row["serie_id"],)).fetchall()]
            else:
                antigos = [saida_id]
            for old in antigos:
                if old not in enviados:
                    con.execute("DELETE FROM saida WHERE id = %s", (old,))

        base = {**comum, "serie_id": serie}
        for l in linhas:
            dados = {**base, "valor": l.get("valor"),
                     "data_vencimento": l.get("data_vencimento"),
                     "data_pagamento": l.get("data_pagamento"),
                     "numero_parcela": l.get("numero_parcela")}
            if l.get("id") and l["id"] in enviados:
                atrib = ", ".join(f"{c} = %s" for c in _COLS_SAIDA)
                con.execute(
                    f"UPDATE saida SET {atrib}, atualizado_em = NOW() WHERE id = %s",
                    _valores_saida(dados) + [l["id"]])
            else:
                _inserir_saida(con, dados)
    fazer_backup()
    return serie


def excluir_saida(saida_id):
    with conexao() as con:
        con.execute("DELETE FROM saida WHERE id = %s", (saida_id,))
    fazer_backup()


def marcar_saida_paga(saida_id, paga, data=None):
    d = (data or "").strip() or date.today().isoformat()
    with conexao() as con:
        con.execute("UPDATE saida SET data_pagamento = %s, atualizado_em = NOW() WHERE id = %s",
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
        return [r["descricao"] for r in con.execute(
            "SELECT DISTINCT descricao FROM saida "
            "WHERE descricao IS NOT NULL AND TRIM(descricao) <> '' "
            "ORDER BY descricao"
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
        a_pagar_mes = _um(con.execute(
            "SELECT COALESCE(SUM(valor), 0) FROM saida "
            "WHERE data_pagamento IS NULL AND substr(data_vencimento, 1, 7) = %s", (mes,)
        ))
        vencido = _um(con.execute(
            "SELECT COALESCE(SUM(valor), 0) FROM saida "
            "WHERE data_pagamento IS NULL AND data_vencimento < %s", (date.today().isoformat(),)
        ))
    return {"a_pagar_mes": a_pagar_mes, "vencido": vencido}


# ---------- entradas (contas a receber = repasses de comissão) ----------

def listar_entradas_repasse(data_ini=None, data_fim=None):
    """Uma linha por PARCELA de repasse — o dinheiro que a Plenus recebe da
    corretora, vinculado à comissão de cada apólice. Junta dois casos:

    * repasse parcelado: linhas de `apolice_repasse`;
    * repasse único / cocorretagem: apólices sem linhas em `apolice_repasse`,
      montadas dos campos "Plenus a receber/recebido/recebido em" da própria
      apólice (parcela rotulada "única").

    `data_ini`/`data_fim` (ISO) recortam pela data da parcela. Situação
    (paga × a receber) é aplicada depois, na camada da rota. Cada dict traz:
    apolice_id, cliente_nome, tipo_seguro_nome, seguradora_nome, numero_apolice,
    premio_liquido, comissao_percentual, parcela, data, valor_previsto,
    valor_recebido, conferido_banco, origem."""
    cols_apolice = (
        "       c.nome AS cliente_nome, t.nome AS tipo_seguro_nome, "
        "       sg.nome AS seguradora_nome, "
        "       a.numero_apolice, a.premio_liquido, a.comissao_percentual, "
        "       COALESCE(a.comissao_cocorretagem, 0) AS comissao_cocorretagem ")
    joins = (" FROM apolice a "
             " LEFT JOIN cliente c     ON c.id = a.cliente_id "
             " LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
             " LEFT JOIN seguradora sg ON sg.id = a.seguradora_id ")
    with conexao() as con:
        parceladas = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       r.parcela, r.data, r.valor_previsto, r.valor_recebido, "
            "       COALESCE(r.conferido_banco, 0) AS conferido_banco "
            "  FROM apolice_repasse r "
            "  JOIN apolice a          ON a.id = r.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " ORDER BY a.id, r.ordem, r.id"
        ).fetchall()
        unicas = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       a.comissao_valor_plenus_receber  AS valor_previsto, "
            "       a.comissao_valor_plenus_recebido AS valor_recebido, "
            "       a.data_plenus_recebido           AS data, "
            "       COALESCE(a.plenus_conferido_banco, 0) AS conferido_banco "
            + joins +
            " WHERE NOT EXISTS (SELECT 1 FROM apolice_repasse r WHERE r.apolice_id = a.id) "
            " ORDER BY a.id"
        ).fetchall()
        # endossos SEM comissão parcelada: repasse "único" dos campos achatados
        endossos = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       e.numero AS _end_num, "
            "       e.comissao_valor_plenus_receber  AS valor_previsto, "
            "       e.comissao_valor_plenus_recebido AS valor_recebido, "
            "       e.data_plenus_recebido           AS data, "
            "       COALESCE(e.plenus_conferido_banco, 0) AS conferido_banco "
            "  FROM apolice_endosso e "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " WHERE COALESCE(e.comissao_parcelada, 0) = 0 "
            " ORDER BY a.id, e.id"
        ).fetchall()
        # endossos COM comissão parcelada: uma linha por parcela de repasse
        endossos_parc = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       e.numero AS _end_num, r.parcela AS _end_parc, "
            "       r.data, r.valor_previsto, r.valor_recebido, "
            "       COALESCE(r.conferido_banco, 0) AS conferido_banco "
            "  FROM apolice_endosso_repasse r "
            "  JOIN apolice_endosso e  ON e.id = r.endosso_id "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " ORDER BY a.id, e.id, r.ordem, r.id"
        ).fetchall()
        cols_cons = (
            "       c.nome AS cliente_nome, tc.nome AS tipo_seguro_nome, "
            "       sg.nome AS seguradora_nome, "
            "       co.numero_grupo, co.numero_cota, co.carta AS premio_liquido, "
            "       co.comissao_percentual, "
            "       COALESCE(co.comissao_cocorretagem, 0) AS comissao_cocorretagem ")
        cons_joins = (" FROM consorcio co "
                      " LEFT JOIN cliente c         ON c.id = co.cliente_id "
                      " LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id "
                      " LEFT JOIN seguradora sg     ON sg.id = co.seguradora_id ")
        # consórcios SEM comissão parcelada: repasse "único" dos campos achatados
        consorcios = con.execute(
            "SELECT co.id AS _cons_id, " + cols_cons + ", "
            "       co.comissao_valor_plenus_receber  AS valor_previsto, "
            "       co.comissao_valor_plenus_recebido AS valor_recebido, "
            "       co.data_plenus_recebido           AS data, "
            "       COALESCE(co.plenus_conferido_banco, 0) AS conferido_banco "
            + cons_joins +
            " WHERE COALESCE(co.comissao_parcelada, 0) = 0 "
            " ORDER BY co.id"
        ).fetchall()
        # consórcios COM comissão parcelada: uma linha por parcela de repasse
        consorcios_parc = con.execute(
            "SELECT co.id AS _cons_id, " + cols_cons + ", "
            "       r.parcela AS _cons_parc, r.data, r.valor_previsto, r.valor_recebido, "
            "       COALESCE(r.conferido_banco, 0) AS conferido_banco "
            "  FROM consorcio_repasse r "
            "  JOIN consorcio co           ON co.id = r.consorcio_id "
            "  LEFT JOIN cliente c         ON c.id = co.cliente_id "
            "  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id "
            "  LEFT JOIN seguradora sg     ON sg.id = co.seguradora_id "
            " ORDER BY co.id, r.ordem, r.id"
        ).fetchall()

    linhas = []
    for row in parceladas:
        d = dict(row)
        d["origem"] = "parcelado"
        linhas.append(d)
    for row in unicas:
        d = dict(row)
        if d.get("valor_previsto") is None and d.get("valor_recebido") is None:
            continue  # apólice sem nenhum dado de repasse — fora do relatório
        d["parcela"] = "única"
        d["origem"] = "unico"
        linhas.append(d)
    for row in endossos:
        d = dict(row)
        if d.get("valor_previsto") is None and d.get("valor_recebido") is None:
            continue  # endosso sem repasse — fora do relatório
        d["parcela"] = ("endosso " + (d.pop("_end_num") or "").strip()).strip()
        d["origem"] = "endosso"
        linhas.append(d)
    for row in endossos_parc:
        d = dict(row)
        num_end = (d.pop("_end_num") or "").strip()
        parc = (d.pop("_end_parc") or "").strip()
        d["parcela"] = ("endosso " + num_end + (" " + parc if parc else "")).strip()
        d["origem"] = "endosso"
        linhas.append(d)
    for row in consorcios:
        d = dict(row)
        if d.get("valor_previsto") is None and d.get("valor_recebido") is None:
            continue
        cid = d.pop("_cons_id")
        d["apolice_id"] = f"cons:{cid}"
        d["consorcio_id"] = cid
        d["is_consorcio"] = True
        d["numero_apolice"] = ("Grupo " + (d.get("numero_grupo") or "—")
                               + (" / cota " + d["numero_cota"] if d.get("numero_cota") else ""))
        d["parcela"] = "consórcio"
        d["origem"] = "consorcio"
        linhas.append(d)
    for row in consorcios_parc:
        d = dict(row)
        cid = d.pop("_cons_id")
        parc = (d.pop("_cons_parc") or "").strip()
        d["apolice_id"] = f"cons:{cid}"
        d["consorcio_id"] = cid
        d["is_consorcio"] = True
        d["numero_apolice"] = ("Grupo " + (d.get("numero_grupo") or "—")
                               + (" / cota " + d["numero_cota"] if d.get("numero_cota") else ""))
        d["parcela"] = ("consórcio " + parc).strip()
        d["origem"] = "consorcio"
        linhas.append(d)

    # o período recorta as parcelas COM data; as parcelas ainda SEM data
    # (a receber, não agendadas) passam sempre — senão sumiriam do relatório
    if data_ini:
        linhas = [l for l in linhas if not l.get("data") or l["data"] >= data_ini]
    if data_fim:
        linhas = [l for l in linhas if not l.get("data") or l["data"] <= data_fim]
    return linhas


def panorama_comissoes(busca=None, data_ini=None, data_fim=None):
    """Uma linha por APÓLICE com os números de comissão (prêmio, %, recebido
    SEGURALTA/Plenus e os totais "no relatório da corretora"). O cálculo do
    esperado e das divergências é feito na camada da rota. Recorte opcional por
    `vigencia_inicio` (ISO) e busca por cliente/número."""
    with conexao() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT a.id AS apolice_id, a.numero_apolice, a.vigencia_inicio, "
            "       c.nome AS cliente_nome, ts.nome AS tipo_seguro_nome, "
            "       COALESCE(s.nome, '(sem seguradora)') AS seguradora_nome, "
            "       a.premio_liquido, a.comissao_percentual, "
            "       COALESCE(a.comissao_cocorretagem, 0) AS cocorretagem, "
            "       CASE WHEN EXISTS (SELECT 1 FROM apolice_comissao cm WHERE cm.apolice_id = a.id) "
            "            THEN (SELECT SUM(cm.valor_recebido) FROM apolice_comissao cm WHERE cm.apolice_id = a.id) "
            "            ELSE a.comissao_valor_seguralta_recebido END AS receb_seguralta, "
            "       CASE WHEN EXISTS (SELECT 1 FROM apolice_repasse r WHERE r.apolice_id = a.id) "
            "            THEN (SELECT SUM(r.valor_recebido) FROM apolice_repasse r WHERE r.apolice_id = a.id) "
            "            ELSE a.comissao_valor_plenus_recebido END AS receb_plenus, "
            "       (SELECT COUNT(DISTINCT cm.parcela) FROM apolice_comissao cm "
            "          WHERE cm.apolice_id = a.id AND cm.valor_recebido IS NOT NULL) AS n_seg_pagas, "
            "       (SELECT COUNT(DISTINCT r.parcela) FROM apolice_repasse r "
            "          WHERE r.apolice_id = a.id AND r.valor_recebido IS NOT NULL) AS n_ple_pagas, "
            "       CASE WHEN EXISTS (SELECT 1 FROM apolice_repasse r WHERE r.apolice_id = a.id) "
            "            THEN (SELECT COALESCE(SUM(r.valor_previsto), 0) FROM apolice_repasse r "
            "                    WHERE r.apolice_id = a.id AND r.valor_recebido IS NULL) "
            "            WHEN a.comissao_valor_plenus_recebido IS NULL "
            "            THEN COALESCE(a.comissao_valor_plenus_receber, 0) "
            "            ELSE 0 END AS ple_a_receber, "
            "       a.recebido_relatorio_seguralta AS rel_receb_seguralta, "
            "       a.recebido_relatorio_plenus    AS rel_receb_plenus "
            "  FROM apolice a "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora s  ON s.id = a.seguradora_id "
            "  LEFT JOIN tipo_seguro ts ON ts.id = a.tipo_seguro_id "
            " ORDER BY seguradora_nome, c.nome, a.id"
        ).fetchall()]
        # endossos com comissão — entram como linhas próprias, ao lado da apólice
        endossos = [dict(r) for r in con.execute(
            "SELECT a.id AS apolice_id, a.numero_apolice, "
            "       COALESCE(e.vigencia_inicio, a.vigencia_inicio) AS vigencia_inicio, "
            "       c.nome AS cliente_nome, ts.nome AS tipo_seguro_nome, "
            "       COALESCE(s.nome, '(sem seguradora)') AS seguradora_nome, "
            "       e.valor AS premio_liquido, e.comissao_percentual, 0 AS cocorretagem, "
            "       CASE WHEN COALESCE(e.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_recebido) FROM apolice_endosso_comissao x WHERE x.endosso_id=e.id) "
            "            ELSE e.comissao_valor_seguralta_recebido END AS receb_seguralta, "
            "       CASE WHEN COALESCE(e.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_recebido) FROM apolice_endosso_repasse x WHERE x.endosso_id=e.id) "
            "            ELSE e.comissao_valor_plenus_recebido END AS receb_plenus, "
            "       (SELECT COUNT(DISTINCT x.parcela) FROM apolice_endosso_repasse x "
            "          WHERE x.endosso_id=e.id AND x.valor_recebido IS NOT NULL) AS n_ple_pagas, "
            "       (SELECT COUNT(DISTINCT x.parcela) FROM apolice_endosso_comissao x "
            "          WHERE x.endosso_id=e.id AND x.valor_recebido IS NOT NULL) AS n_seg_pagas, "
            "       CASE WHEN COALESCE(e.comissao_parcelada,0)=1 "
            "            THEN (SELECT COALESCE(SUM(x.valor_previsto),0) FROM apolice_endosso_repasse x "
            "                    WHERE x.endosso_id=e.id AND x.valor_recebido IS NULL) "
            "            WHEN COALESCE(e.comissao_valor_plenus_receber,0) - COALESCE(e.comissao_valor_plenus_recebido,0) > 0 "
            "            THEN COALESCE(e.comissao_valor_plenus_receber,0) - COALESCE(e.comissao_valor_plenus_recebido,0) "
            "            ELSE 0 END AS ple_a_receber, "
            "       NULL AS rel_receb_seguralta, NULL AS rel_receb_plenus, "
            "       1 AS is_endosso, e.numero AS endosso_numero, e.id AS endosso_id, "
            "       CASE WHEN COALESCE(e.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_previsto) FROM apolice_endosso_comissao x WHERE x.endosso_id=e.id) "
            "            ELSE e.comissao_valor_seguralta_receber END AS end_com_seg, "
            "       CASE WHEN COALESCE(e.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_previsto) FROM apolice_endosso_repasse x WHERE x.endosso_id=e.id) "
            "            ELSE e.comissao_valor_plenus_receber END AS end_com_ple "
            "  FROM apolice_endosso e "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora s  ON s.id = a.seguradora_id "
            "  LEFT JOIN tipo_seguro ts ON ts.id = a.tipo_seguro_id "
            " WHERE COALESCE(e.comissao_parcelada, 0) = 1 "
            "    OR e.comissao_percentual IS NOT NULL "
            "    OR e.comissao_valor_seguralta_receber IS NOT NULL "
            "    OR e.comissao_valor_seguralta_recebido IS NOT NULL "
            "    OR e.comissao_valor_plenus_receber IS NOT NULL "
            "    OR e.comissao_valor_plenus_recebido IS NOT NULL"
        ).fetchall()]
        # consórcios com comissão — linhas próprias (comissão sobre o valor da carta)
        consorcios = [dict(r) for r in con.execute(
            "SELECT co.id AS consorcio_id, NULL AS numero_apolice, co.numero_grupo, co.numero_cota, "
            "       COALESCE(co.data_plenus_recebido, co.data_seguralta_recebido, substr(co.criado_em,1,10)) AS vigencia_inicio, "
            "       c.nome AS cliente_nome, tc.nome AS tipo_seguro_nome, "
            "       COALESCE(s.nome, '(sem seguradora)') AS seguradora_nome, "
            "       co.carta AS premio_liquido, co.comissao_percentual, "
            "       COALESCE(co.comissao_cocorretagem, 0) AS cocorretagem, "
            "       CASE WHEN COALESCE(co.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_recebido) FROM consorcio_comissao x WHERE x.consorcio_id=co.id) "
            "            ELSE co.comissao_valor_seguralta_recebido END AS receb_seguralta, "
            "       CASE WHEN COALESCE(co.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_recebido) FROM consorcio_repasse x WHERE x.consorcio_id=co.id) "
            "            ELSE co.comissao_valor_plenus_recebido END AS receb_plenus, "
            "       (SELECT COUNT(DISTINCT x.parcela) FROM consorcio_repasse x "
            "          WHERE x.consorcio_id=co.id AND x.valor_recebido IS NOT NULL) AS n_ple_pagas, "
            "       (SELECT COUNT(DISTINCT x.parcela) FROM consorcio_comissao x "
            "          WHERE x.consorcio_id=co.id AND x.valor_recebido IS NOT NULL) AS n_seg_pagas, "
            "       CASE WHEN COALESCE(co.comissao_parcelada,0)=1 "
            "            THEN (SELECT COALESCE(SUM(x.valor_previsto),0) FROM consorcio_repasse x "
            "                    WHERE x.consorcio_id=co.id AND x.valor_recebido IS NULL) "
            "            WHEN COALESCE(co.comissao_valor_plenus_receber,0) - COALESCE(co.comissao_valor_plenus_recebido,0) > 0 "
            "            THEN COALESCE(co.comissao_valor_plenus_receber,0) - COALESCE(co.comissao_valor_plenus_recebido,0) "
            "            ELSE 0 END AS ple_a_receber, "
            "       co.recebido_relatorio_seguralta AS rel_receb_seguralta, "
            "       co.recebido_relatorio_plenus    AS rel_receb_plenus, "
            "       1 AS is_consorcio, co.numero_grupo AS consorcio_grupo, "
            "       CASE WHEN COALESCE(co.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_previsto) FROM consorcio_comissao x WHERE x.consorcio_id=co.id) "
            "            ELSE co.comissao_valor_seguralta_receber END AS end_com_seg, "
            "       CASE WHEN COALESCE(co.comissao_parcelada,0)=1 "
            "            THEN (SELECT SUM(x.valor_previsto) FROM consorcio_repasse x WHERE x.consorcio_id=co.id) "
            "            ELSE co.comissao_valor_plenus_receber END AS end_com_ple "
            "  FROM consorcio co "
            "  LEFT JOIN cliente c        ON c.id = co.cliente_id "
            "  LEFT JOIN seguradora s     ON s.id = co.seguradora_id "
            "  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id "
            " WHERE COALESCE(co.comissao_parcelada, 0) = 1 "
            "    OR co.comissao_percentual IS NOT NULL "
            "    OR co.comissao_valor_seguralta_receber IS NOT NULL "
            "    OR co.comissao_valor_seguralta_recebido IS NOT NULL "
            "    OR co.comissao_valor_plenus_receber IS NOT NULL "
            "    OR co.comissao_valor_plenus_recebido IS NOT NULL"
        ).fetchall()]
    rows += endossos
    rows += consorcios
    if data_ini:
        rows = [r for r in rows if (r.get("vigencia_inicio") or "") >= data_ini]
    if data_fim:
        rows = [r for r in rows if (r.get("vigencia_inicio") or "") <= data_fim]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        rows = [r for r in rows
                if alvo in _sem_acento_minusculo(r.get("cliente_nome") or "")
                or alvo in _sem_acento_minusculo(r.get("numero_apolice") or "")]
    return rows


def repasse_vs_relatorio_plenus():
    """Por apólice, compara a SOMA do repasse no sistema (todas as parcelas de
    `apolice_repasse`, sem recorte de período) com os totais "no relatório da
    corretora" (`apolice.previsto_relatorio_plenus` / `recebido_relatorio_plenus`).
    Só entra apólice que tem ao menos um desses dois totais preenchido.
    Devolve {apolice_id: {prev_sistema, prev_relatorio, receb_sistema, receb_relatorio}}."""
    with conexao() as con:
        rows = con.execute(
            "SELECT a.id AS apolice_id, "
            "       a.previsto_relatorio_plenus  AS prev_relatorio, "
            "       a.recebido_relatorio_plenus  AS receb_relatorio, "
            "       COALESCE((SELECT SUM(r.valor_previsto) FROM apolice_repasse r "
            "                   WHERE r.apolice_id = a.id), 0) AS prev_sistema, "
            "       COALESCE((SELECT SUM(r.valor_recebido) FROM apolice_repasse r "
            "                   WHERE r.apolice_id = a.id), 0) AS receb_sistema "
            "  FROM apolice a "
            " WHERE a.previsto_relatorio_plenus IS NOT NULL "
            "    OR a.recebido_relatorio_plenus IS NOT NULL"
        ).fetchall()
    return {r["apolice_id"]: dict(r) for r in rows}


def comissoes_repasses_por_apolice(data_ini=None, data_fim=None):
    """Uma entrada por APÓLICE com dado de comissão, trazendo as DUAS tabelas
    (lado Seguralta = `apolice_comissao`; lado Plenus = `apolice_repasse`) para a
    grade editável do menu Entradas. Junta os mesmos dois casos do relatório:

    * parcelada (`comissao_parcelada = 1`): as linhas reais das duas tabelas;
    * único / cocorretagem: uma linha "única" sintetizada dos campos achatados
      da própria apólice (lado Seguralta sem data — não existe coluna pra isso).

    `data_ini`/`data_fim` (ISO) filtram QUAIS apólices entram (tem ao menos uma
    parcela com `data` no intervalo, ou tem parcela sem data). NÃO recortam as
    linhas de dentro do bloco — o "salvar" regrava a tabela inteira da apólice."""
    cols_apolice = (
        "       c.nome AS cliente_nome, a.tipo_seguro_id, t.nome AS tipo_seguro_nome, "
        "       sg.nome AS seguradora_nome, "
        "       a.numero_apolice, a.premio_liquido, a.comissao_percentual, "
        "       COALESCE(a.comissao_parcelada, 0)    AS comissao_parcelada, "
        "       COALESCE(a.comissao_cocorretagem, 0) AS comissao_cocorretagem ")
    with conexao() as con:
        apolices = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       a.comissao_valor_seguralta_receber, a.comissao_valor_seguralta_recebido, "
            "       a.comissao_valor_plenus_receber,   a.comissao_valor_plenus_recebido, "
            "       a.data_seguralta_recebido, a.data_plenus_recebido, "
            "       COALESCE(a.plenus_conferido_banco, 0) AS plenus_conferido_banco "
            "  FROM apolice a "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " ORDER BY a.id"
        ).fetchall()
        comissoes = con.execute(
            "SELECT apolice_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM apolice_comissao ORDER BY apolice_id, ordem, id"
        ).fetchall()
        repasses = con.execute(
            "SELECT apolice_id, parcela, valor_previsto, valor_recebido, data, "
            "       COALESCE(conferido_banco, 0) AS conferido_banco "
            "  FROM apolice_repasse ORDER BY apolice_id, ordem, id"
        ).fetchall()
        end_com = con.execute(
            "SELECT endosso_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM apolice_endosso_comissao ORDER BY endosso_id, ordem, id").fetchall()
        end_rep = con.execute(
            "SELECT endosso_id, parcela, valor_previsto, valor_recebido, data, "
            "       COALESCE(conferido_banco, 0) AS conferido_banco "
            "  FROM apolice_endosso_repasse ORDER BY endosso_id, ordem, id").fetchall()
        endossos = con.execute(
            "SELECT e.id AS endosso_id, e.numero AS endosso_numero, e.apolice_id, "
            "       c.nome AS cliente_nome, a.tipo_seguro_id, t.nome AS tipo_seguro_nome, "
            "       sg.nome AS seguradora_nome, a.numero_apolice, "
            "       e.valor AS premio_liquido, e.comissao_percentual, "
            "       COALESCE(e.comissao_parcelada, 0) AS comissao_parcelada, 0 AS comissao_cocorretagem, "
            "       e.comissao_valor_seguralta_receber, e.comissao_valor_seguralta_recebido, "
            "       e.comissao_valor_plenus_receber, e.comissao_valor_plenus_recebido, "
            "       e.data_seguralta_recebido, e.data_plenus_recebido, "
            "       COALESCE(e.plenus_conferido_banco, 0) AS plenus_conferido_banco "
            "  FROM apolice_endosso e "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " ORDER BY e.id"
        ).fetchall()
        cons_com = con.execute(
            "SELECT consorcio_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM consorcio_comissao ORDER BY consorcio_id, ordem, id").fetchall()
        cons_rep = con.execute(
            "SELECT consorcio_id, parcela, valor_previsto, valor_recebido, data, "
            "       COALESCE(conferido_banco, 0) AS conferido_banco "
            "  FROM consorcio_repasse ORDER BY consorcio_id, ordem, id").fetchall()
        consorcios = con.execute(
            "SELECT co.id AS consorcio_id, co.numero_grupo, co.numero_cota, "
            "       c.nome AS cliente_nome, NULL AS tipo_seguro_id, tc.nome AS tipo_seguro_nome, "
            "       sg.nome AS seguradora_nome, "
            "       co.carta AS premio_liquido, co.comissao_percentual, "
            "       COALESCE(co.comissao_parcelada, 0) AS comissao_parcelada, "
            "       COALESCE(co.comissao_cocorretagem, 0) AS comissao_cocorretagem, "
            "       co.comissao_valor_seguralta_receber, co.comissao_valor_seguralta_recebido, "
            "       co.comissao_valor_plenus_receber, co.comissao_valor_plenus_recebido, "
            "       co.data_seguralta_recebido, co.data_plenus_recebido, "
            "       COALESCE(co.plenus_conferido_banco, 0) AS plenus_conferido_banco "
            "  FROM consorcio co "
            "  LEFT JOIN cliente c        ON c.id = co.cliente_id "
            "  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id "
            "  LEFT JOIN seguradora sg    ON sg.id = co.seguradora_id "
            " ORDER BY co.id"
        ).fetchall()

    por_apolice_com, por_apolice_rep = {}, {}
    for r in comissoes:
        por_apolice_com.setdefault(r["apolice_id"], []).append(dict(r))
    for r in repasses:
        por_apolice_rep.setdefault(r["apolice_id"], []).append(dict(r))
    por_end_com, por_end_rep = {}, {}
    for r in end_com:
        por_end_com.setdefault(r["endosso_id"], []).append(dict(r))
    for r in end_rep:
        por_end_rep.setdefault(r["endosso_id"], []).append(dict(r))
    por_cons_com, por_cons_rep = {}, {}
    for r in cons_com:
        por_cons_com.setdefault(r["consorcio_id"], []).append(dict(r))
    for r in cons_rep:
        por_cons_rep.setdefault(r["consorcio_id"], []).append(dict(r))

    def _no_periodo(linhas):
        """True se alguma linha tem data no intervalo, ou tem linha sem data."""
        if not data_ini and not data_fim:
            return True
        algum_com_data = False
        for l in linhas:
            d = l.get("data")
            if not d:
                return True
            algum_com_data = True
            if (not data_ini or d >= data_ini) and (not data_fim or d <= data_fim):
                return True
        return not algum_com_data

    saida = []
    for row in apolices:
        ap = dict(row)
        aid = ap["apolice_id"]
        if ap["comissao_parcelada"]:
            com = por_apolice_com.get(aid, [])
            rep = por_apolice_rep.get(aid, [])
            if not com and not rep:
                continue
        else:
            valores = (ap["comissao_valor_seguralta_receber"], ap["comissao_valor_seguralta_recebido"],
                       ap["comissao_valor_plenus_receber"], ap["comissao_valor_plenus_recebido"])
            if all(v is None for v in valores):
                continue
            com = [{"parcela": "única",
                    "valor_previsto": ap["comissao_valor_seguralta_receber"],
                    "valor_recebido": ap["comissao_valor_seguralta_recebido"],
                    "data": ap["data_seguralta_recebido"]}]
            rep = [{"parcela": "única",
                    "valor_previsto": ap["comissao_valor_plenus_receber"],
                    "valor_recebido": ap["comissao_valor_plenus_recebido"],
                    "data": ap["data_plenus_recebido"],
                    "conferido_banco": ap["plenus_conferido_banco"]}]
        if not _no_periodo(com + rep):
            continue
        ap["comissoes"] = com
        ap["repasses"] = rep
        saida.append(ap)

    for row in endossos:
        e = dict(row)
        eid = e["endosso_id"]
        if e["comissao_parcelada"]:
            com = por_end_com.get(eid, [])
            rep = por_end_rep.get(eid, [])
            if not com and not rep:
                continue
        else:
            valores = (e["comissao_valor_seguralta_receber"], e["comissao_valor_seguralta_recebido"],
                       e["comissao_valor_plenus_receber"], e["comissao_valor_plenus_recebido"])
            if all(v is None for v in valores):
                continue
            rot = ("endosso " + (e["endosso_numero"] or "")).strip()
            com = [{"parcela": rot,
                    "valor_previsto": e["comissao_valor_seguralta_receber"],
                    "valor_recebido": e["comissao_valor_seguralta_recebido"],
                    "data": e["data_seguralta_recebido"]}]
            rep = [{"parcela": rot,
                    "valor_previsto": e["comissao_valor_plenus_receber"],
                    "valor_recebido": e["comissao_valor_plenus_recebido"],
                    "data": e["data_plenus_recebido"],
                    "conferido_banco": e["plenus_conferido_banco"]}]
        if not _no_periodo(com + rep):
            continue
        e["is_endosso"] = True
        e["comissoes"] = com
        e["repasses"] = rep
        saida.append(e)

    for row in consorcios:
        co = dict(row)
        cid = co["consorcio_id"]
        rot = ("consórcio grupo " + (co["numero_grupo"] or "")).strip()
        if co["comissao_parcelada"]:
            com = por_cons_com.get(cid, [])
            rep = por_cons_rep.get(cid, [])
            if not com and not rep:
                continue
        else:
            valores = (co["comissao_valor_seguralta_receber"], co["comissao_valor_seguralta_recebido"],
                       co["comissao_valor_plenus_receber"], co["comissao_valor_plenus_recebido"])
            if all(v is None for v in valores):
                continue
            com = [{"parcela": rot,
                    "valor_previsto": co["comissao_valor_seguralta_receber"],
                    "valor_recebido": co["comissao_valor_seguralta_recebido"],
                    "data": co["data_seguralta_recebido"]}]
            rep = [{"parcela": rot,
                    "valor_previsto": co["comissao_valor_plenus_receber"],
                    "valor_recebido": co["comissao_valor_plenus_recebido"],
                    "data": co["data_plenus_recebido"],
                    "conferido_banco": co["plenus_conferido_banco"]}]
        if not _no_periodo(com + rep):
            continue
        co["is_consorcio"] = True
        co["apolice_id"] = f"cons:{cid}"
        co["consorcio_grupo"] = co.get("numero_grupo")
        co["numero_apolice"] = ("Grupo " + (co.get("numero_grupo") or "—")
                                + (" / cota " + co["numero_cota"] if co.get("numero_cota") else ""))
        co["comissoes"] = com
        co["repasses"] = rep
        saida.append(co)
    return saida
