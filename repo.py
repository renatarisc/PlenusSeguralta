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


def contar_usuarios_ativos():
    with conexao() as con:
        return _um(con.execute("SELECT COUNT(*) FROM usuario WHERE ativo = 1"))


def usuario_ativo(uid):
    """True se o usuário existe e está ativo (checado a cada requisição)."""
    with conexao() as con:
        r = con.execute("SELECT ativo FROM usuario WHERE id = %s", (uid,)).fetchone()
    return bool(r and r["ativo"])


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
    "tel_ddd", "tel_numero", "email", "status_cliente_id", "observacao", "data_contato",
)


def _valores_cliente(dados):
    valores = []
    for col in _COLS_CLIENTE:
        v = (dados.get(col) or "").strip()
        if col == "tipo_pessoa":
            valores.append("J" if v.upper() == "J" else "F")  # NOT NULL: sempre F ou J
            continue
        if col == "status_cliente_id":
            valores.append(int(v) if v.isdigit() else None)
            continue
        if col in ("cpf", "end_cep", "tel_ddd", "tel_numero"):
            v = so_digitos(v)
        valores.append(v or None)
    return valores


def listar_clientes(busca=None, uf=None, cidade=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT c.id, c.nome, c.tipo_pessoa, c.cpf, c.end_cidade, c.end_estado, "
            "       c.tel_ddd, c.tel_numero, c.email, sc.nome AS status_cliente_nome "
            "  FROM cliente c "
            "  LEFT JOIN status_cliente sc ON sc.id = c.status_cliente_id "
            " ORDER BY c.nome"
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
    for r in rows:
        m.setdefault(r["cliente_id"], set()).add(r["nome"] or "(sem tipo)")
    return {k: sorted(v, key=_sem_acento_minusculo) for k, v in m.items()}


def seguradoras_por_cliente():
    """{cliente_id: [nomes de seguradora das apólices do cliente]} — p/ agrupar
    a lista de clientes por seguradora (cliente com apólices de várias entra em várias)."""
    with conexao() as con:
        rows = con.execute(
            "SELECT DISTINCT a.cliente_id, s.nome "
            "  FROM apolice a "
            "  LEFT JOIN seguradora s ON s.id = a.seguradora_id "
            " WHERE a.cliente_id IS NOT NULL"
        ).fetchall()
    m = {}
    for r in rows:
        m.setdefault(r["cliente_id"], set()).add(r["nome"] or "(sem seguradora)")
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


def cliente_por_nome(nome, ignorar_id=None):
    """Cliente que já tem esse nome (comparação sem acento/maiúsculas/espaços nas pontas) -> {id, nome}, ou None."""
    nome = (nome or "").strip()
    if not nome:
        return None
    sql = "SELECT id, nome FROM cliente WHERE LOWER(TRIM(nome)) = LOWER(TRIM(%s))"
    params = [nome]
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

_TABELAS_SIMPLES = {"tipo_seguro", "forma_pagamento", "seguradora", "categoria_saida",
                     "tipo_consorcio", "status_cliente", "conta_origem", "status_apolice",
                     "tipo_servico"}


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


def reordenar_campos_cotacao(ids_em_ordem):
    """Redefine a ordem de cada campo em `ids_em_ordem` pra 1, 2, 3... nessa sequência
    (usado pelo arrastar-e-soltar da lista). Só mexe nos ids recebidos."""
    with conexao() as con:
        for posicao, campo_id in enumerate(ids_em_ordem, start=1):
            con.execute("UPDATE cotacao_campo SET ordem = %s WHERE id = %s", (posicao, int(campo_id)))
    fazer_backup()


def excluir_campo_cotacao(campo_id):
    with conexao() as con:
        con.execute("DELETE FROM cotacao_campo WHERE id = %s", (campo_id,))
    fazer_backup()


# ---------- apólice (+ parcelas) ----------

_COLS_APOLICE = (
    "cliente_id", "seguradora_id", "tipo_seguro_id", "status_apolice_id", "numero_apolice",
    "vigencia_inicio", "vigencia_fim",
    "premio_liquido", "iof", "premio_total",
    "forma_pagamento_id", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "recibo_id",
    "comissao_parcelada", "comissao_cocorretagem", "data_deposito_cc",
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


def _cartao_enviado_valor(v):
    return 2 if str(v or "").strip() == "2" else _sim_nao(v)


def _valores_apolice(dados):
    cartao_enviado = _cartao_enviado_valor(dados.get("cartao_enviado"))
    return [
        _int_ou_none(dados.get("cliente_id")),
        _int_ou_none(dados.get("seguradora_id")),
        _int_ou_none(dados.get("tipo_seguro_id")),
        _int_ou_none(dados.get("status_apolice_id")),
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
        _int_ou_none(dados.get("recibo_id")),
        _sim_nao(dados.get("comissao_parcelada")),
        _sim_nao(dados.get("comissao_cocorretagem")),
        (dados.get("data_deposito_cc") or "").strip() or None,
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
        cartao_enviado,
        None if cartao_enviado == 2 else (dados.get("cartao_enviado_data") or "").strip() or None,
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


def _sincronizar_parcelas(con, tabela, col_dono, dono_id, parcelas):
    """Grava as parcelas vindas do formulário SEM apagar e recriar as que já existem:
    a linha com `id` (parcela deste dono) é atualizada no lugar, o que preserva o id — e
    com ele o histórico de avisos (notificacao_*, ON DELETE CASCADE) e o evento da agenda —
    e as datas pago_em/aviso_ok_em/enviado_em (só mudam quando a marcação muda).
    Linha sem id (ou com id que não é deste dono) entra como nova; parcela que não veio
    mais no formulário foi removida pelo usuário e é apagada."""
    hoje = date.today().isoformat()
    atuais = {r["id"]: r for r in con.execute(
        f"SELECT id, paga, pago_em, aviso_ok, aviso_ok_em, enviado, enviado_em "
        f"FROM {tabela} WHERE {col_dono} = %s", (dono_id,)).fetchall()}
    mantidos = set()
    for p in parcelas or []:
        pid = _int_ou_none(p.get("id"))
        ant = atuais.get(pid) if pid not in mantidos else None
        marc = {}
        for flag, col_em in (("paga", "pago_em"), ("aviso_ok", "aviso_ok_em"),
                             ("enviado", "enviado_em")):
            v = 1 if p.get(flag) in (1, "1", True, "sim", "on") else 0
            if not v:
                em = None
            elif ant and ant[flag] and ant[col_em]:
                em = ant[col_em]                 # já estava marcada: mantém a data original
            else:
                em = (p.get(col_em) or "").strip() or hoje
            marc[flag], marc[col_em] = v, em
        valores = (p.get("identificacao"), p.get("data"), p.get("valor"),
                   marc["paga"], marc["pago_em"], marc["aviso_ok"], marc["aviso_ok_em"],
                   marc["enviado"], marc["enviado_em"])
        if ant:
            con.execute(
                f"UPDATE {tabela} SET identificacao = %s, data = %s, valor = %s, paga = %s, "
                f"pago_em = %s, aviso_ok = %s, aviso_ok_em = %s, enviado = %s, enviado_em = %s "
                f"WHERE id = %s", valores + (pid,))
            mantidos.add(pid)
        else:
            con.execute(
                f"INSERT INTO {tabela} ({col_dono}, identificacao, data, valor, paga, pago_em, "
                f"aviso_ok, aviso_ok_em, enviado, enviado_em) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (dono_id,) + valores)
    for pid in set(atuais) - mantidos:
        con.execute(f"DELETE FROM {tabela} WHERE id = %s", (pid,))


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
        con.execute(
            "INSERT INTO apolice_repasse "
            "(apolice_id, parcela, valor_previsto, valor_recebido, data, recibo_id, "
            " data_deposito_cc, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (apolice_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), _int_ou_none(r.get("recibo_id")),
             r.get("data_deposito_cc"), i),
        )


def listar_apolices(cliente_id=None, tipo_seguro_id=None, mes_inicio=None, quiver=None,
                    busca=None, parcela_status=None, mes_fim=None, ordem=None,
                    forma_pagamento_id=None, seguradora_id=None, status_apolice_id=None,
                    apolice_enviada=None, cartao_enviado=None):
    sql = """SELECT a.id, a.numero_apolice, a.vigencia_inicio, a.vigencia_fim,
                    a.premio_liquido, a.lancado_quiver, a.aviso_vigencia_ok, a.cliente_id,
                    a.status_apolice_id,
                    c.nome AS cliente_nome, c.tipo_pessoa AS cliente_tipo_pessoa,
                    t.nome AS tipo_seguro_nome,
                    s.nome AS seguradora_nome,
                    sa.nome AS status_apolice_nome,
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
               LEFT JOIN seguradora s  ON s.id = a.seguradora_id
               LEFT JOIN status_apolice sa ON sa.id = a.status_apolice_id"""
    filtros, params = [], []
    if cliente_id:
        filtros.append("a.cliente_id = %s")
        params.append(cliente_id)
    if tipo_seguro_id:
        filtros.append("a.tipo_seguro_id = %s")
        params.append(tipo_seguro_id)
    if seguradora_id:
        filtros.append("a.seguradora_id = %s")
        params.append(seguradora_id)
    if status_apolice_id:
        filtros.append("a.status_apolice_id = %s")
        params.append(status_apolice_id)
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
    if apolice_enviada in (0, 1, True, False):
        filtros.append("COALESCE(a.apolice_enviada, 0) = %s")
        params.append(1 if apolice_enviada in (1, True) else 0)
    if cartao_enviado in (0, 1, 2):
        filtros.append("COALESCE(a.cartao_enviado, 0) = %s")
        params.append(cartao_enviado)
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


def apolices_por_seguradora():
    """[{nome, qtd}] ordenado da maior qtd pra menor; apólice sem seguradora vira '(sem seguradora)'."""
    with conexao() as con:
        linhas = con.execute(
            "SELECT COALESCE(s.nome, '(sem seguradora)') AS nome, COUNT(*) AS qtd "
            "  FROM apolice a LEFT JOIN seguradora s ON s.id = a.seguradora_id "
            " GROUP BY COALESCE(s.nome, '(sem seguradora)') "
            " ORDER BY qtd DESC, nome"
        ).fetchall()
        return [dict(l) for l in linhas]


def apolices_datas_vigencia():
    """Só o necessário p/ contar avisos de vigência (contador do menu, roda em toda página)."""
    with conexao() as con:
        return [dict(l) for l in con.execute(
            "SELECT id, vigencia_inicio, vigencia_fim, aviso_vigencia_ok FROM apolice"
        ).fetchall()]


# ---------- regras de aviso ----------

def regras_aviso():
    with conexao() as con:
        return {l["tipo"]: dict(l) for l in con.execute("SELECT * FROM regra_aviso").fetchall()}


def destinatarios_email():
    """Lista salva pela tela Avisos, ou None se nunca foi salva (vale a do plenus_config.json)."""
    with conexao() as con:
        l = con.execute("SELECT valor FROM config_sistema WHERE chave = 'email_destinatarios'").fetchone()
    if l is None:
        return None
    return [e for e in (l["valor"] or "").splitlines() if e.strip()]


def salvar_regras_aviso(regras, destinatarios):
    """`regras`: {tipo: {ativo, campo_base, dias_inicio, dias_parar_apos, avisar_sem_data}};
    `destinatarios`: lista de e-mails do aviso diário."""
    with conexao() as con:
        con.execute(
            "INSERT INTO config_sistema (chave, valor) VALUES ('email_destinatarios', %s) "
            "ON DUPLICATE KEY UPDATE valor = VALUES(valor)",
            ("\n".join(destinatarios),),
        )
        for tipo, r in regras.items():
            con.execute(
                "UPDATE regra_aviso SET ativo = %s, campo_base = %s, dias_inicio = %s, "
                "dias_parar_apos = %s, avisar_sem_data = %s WHERE tipo = %s",
                (r["ativo"], r["campo_base"], r["dias_inicio"], r["dias_parar_apos"],
                 r["avisar_sem_data"], tipo),
            )
    fazer_backup()


def obter_apolice(apolice_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM apolice WHERE id = %s", (apolice_id,)).fetchone()
        if not l:
            return None
        ap = dict(l)
        if ap.get("recibo_id"):
            rec = con.execute("SELECT numero FROM recibo WHERE id = %s", (ap["recibo_id"],)).fetchone()
            ap["recibo_numero"] = rec["numero"] if rec else None
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
            "SELECT r.id, r.parcela, r.valor_previsto, r.valor_recebido, r.data, r.recibo_id, "
            "       r.data_deposito_cc, rec.numero AS recibo_numero "
            "FROM apolice_repasse r LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            "WHERE r.apolice_id = %s ORDER BY r.ordem, r.id",
            (apolice_id,),
        ).fetchall()]
        return ap


def _tabela_parcela(origem):
    return {"endosso": "apolice_endosso_parcela",
            "consorcio": "consorcio_boleto",
            "servico": "servico_parcela"}.get(origem, "apolice_parcela")


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
        _sincronizar_parcelas(con, "apolice_parcela", "apolice_id", apolice_id, parcelas)
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
    "data_seguralta_recebido", "data_plenus_recebido", "recibo_id",
    "comissao_cocorretagem", "data_deposito_cc",
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
        _int_ou_none(d.get("recibo_id")),
        _sim_nao(d.get("comissao_cocorretagem")),
        (d.get("data_deposito_cc") or "").strip() or None,
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
        con.execute(
            "INSERT INTO apolice_endosso_repasse "
            "(endosso_id, parcela, valor_previsto, valor_recebido, data, recibo_id, "
            " data_deposito_cc, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (endosso_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), _int_ou_none(r.get("recibo_id")),
             r.get("data_deposito_cc"), i))


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


def listar_endossos(apolice_id=None, busca=None, quiver=None):
    sql, params = _SQL_ENDOSSO_SEL, []
    filtros = []
    if apolice_id:
        filtros.append("e.apolice_id = %s")
        params.append(apolice_id)
    if quiver in (0, 1, True, False):
        filtros.append("COALESCE(e.lancado_quiver, 0) = %s")
        params.append(1 if quiver in (1, True) else 0)
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
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
        if e.get("recibo_id"):
            rec = con.execute("SELECT numero FROM recibo WHERE id = %s", (e["recibo_id"],)).fetchone()
            e["recibo_numero"] = rec["numero"] if rec else None
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
            "SELECT r.id, r.parcela, r.valor_previsto, r.valor_recebido, r.data, r.recibo_id, "
            "       r.data_deposito_cc, rec.numero AS recibo_numero "
            "FROM apolice_endosso_repasse r LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            "WHERE r.endosso_id = %s ORDER BY r.ordem, r.id",
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
        _sincronizar_parcelas(con, "apolice_endosso_parcela", "endosso_id", endosso_id, parcelas)
        for tab in ("apolice_endosso_comissao", "apolice_endosso_repasse"):
            con.execute(f"DELETE FROM {tab} WHERE endosso_id = %s", (endosso_id,))
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
    "comissao_parcelada", "comissao_cocorretagem", "data_deposito_cc",
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
        (d.get("data_deposito_cc") or "").strip() or None,
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
            "(consorcio_id, parcela, valor_previsto, valor_recebido, data, conferido_banco, "
            " data_deposito_cc, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (consorcio_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), conf, r.get("data_deposito_cc"), i))


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


def _sincronizar_consorcio_boletos(con, consorcio_id, boletos):
    """Mesma ideia de `_sincronizar_parcelas`, para os boletos do consórcio: atualiza no
    lugar os que já existem (preserva id, histórico de avisos e aviso_ok_em)."""
    hoje = date.today().isoformat()
    atuais = {r["id"]: r for r in con.execute(
        "SELECT id, aviso_ok, aviso_ok_em FROM consorcio_boleto WHERE consorcio_id = %s",
        (consorcio_id,)).fetchall()}
    mantidos = set()
    for i, b in enumerate(boletos or []):
        bid = _int_ou_none(b.get("id"))
        ant = atuais.get(bid) if bid not in mantidos else None
        pago_em = (b.get("data_pagamento") or "").strip() or None
        _st = (b.get("status") or "").strip()
        status = "pago" if pago_em else (_st if _st in ("a_enviar", "enviado", "pago") else "a_enviar")
        aviso = 1 if b.get("aviso_ok") in (1, "1", True, "sim", "on") else 0
        if not aviso:
            aviso_em = None
        elif ant and ant["aviso_ok"] and ant["aviso_ok_em"]:
            aviso_em = ant["aviso_ok_em"]
        else:
            aviso_em = (b.get("aviso_ok_em") or "").strip() or hoje
        valores = (b.get("identificacao"), b.get("valor"),
                   (b.get("data_emissao") or "").strip() or None,
                   (b.get("data_vencimento") or "").strip() or None,
                   pago_em, status, aviso, aviso_em, i)
        if ant:
            con.execute(
                "UPDATE consorcio_boleto SET identificacao = %s, valor = %s, data_emissao = %s, "
                "data_vencimento = %s, data_pagamento = %s, status = %s, aviso_ok = %s, "
                "aviso_ok_em = %s, ordem = %s WHERE id = %s", valores + (bid,))
            mantidos.add(bid)
        else:
            con.execute(
                "INSERT INTO consorcio_boleto "
                "(consorcio_id, identificacao, valor, data_emissao, data_vencimento, "
                " data_pagamento, status, aviso_ok, aviso_ok_em, ordem) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (consorcio_id,) + valores)
    for bid in set(atuais) - mantidos:
        con.execute("DELETE FROM consorcio_boleto WHERE id = %s", (bid,))


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


def listar_consorcios(busca=None, quiver=None):
    sql = _SQL_CONSORCIO_SEL
    params = []
    if quiver in (0, 1, True, False):
        sql += " WHERE COALESCE(co.lancado_quiver, 0) = %s"
        params.append(1 if quiver in (1, True) else 0)
    sql += " ORDER BY co.criado_em DESC, co.id DESC"
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(sql, params).fetchall()]
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
            "SELECT id, parcela, valor_previsto, valor_recebido, data, conferido_banco, "
            "       data_deposito_cc "
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
        for tab in ("consorcio_parcela_valor", "consorcio_comissao", "consorcio_repasse"):
            con.execute(f"DELETE FROM {tab} WHERE consorcio_id = %s", (consorcio_id,))
        _inserir_consorcio_parcela_valores(con, consorcio_id, parcela_valores)
        _inserir_consorcio_comissoes(con, consorcio_id, comissoes)
        _inserir_consorcio_repasses(con, consorcio_id, repasses)
        _sincronizar_consorcio_boletos(con, consorcio_id, boletos)
    fazer_backup()


def excluir_consorcio(consorcio_id):
    with conexao() as con:
        con.execute("DELETE FROM consorcio WHERE id = %s", (consorcio_id,))
    fazer_backup()


# ---------- serviços (assistência, vidros, rastreador... ligados ao carro do cliente) ----------

_COLS_SERVICO = (
    "cliente_id", "apolice_id", "seguradora_id", "tipo_servico_id", "status_apolice_id",
    "numero_proposta", "vigencia_inicio", "vigencia_fim",
    "premio_liquido", "iof", "premio_total",
    "forma_pagamento_id", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "recibo_id",
    "comissao_parcelada", "comissao_cocorretagem", "data_deposito_cc",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive", "observacao",
)


def _valores_servico(d):
    return [
        _int_ou_none(d.get("cliente_id")),
        _int_ou_none(d.get("apolice_id")),
        _int_ou_none(d.get("seguradora_id")),
        _int_ou_none(d.get("tipo_servico_id")),
        _int_ou_none(d.get("status_apolice_id")),
        (d.get("numero_proposta") or "").strip() or None,
        (d.get("vigencia_inicio") or "").strip() or None,
        (d.get("vigencia_fim") or "").strip() or None,
        para_decimal(d.get("premio_liquido")),
        para_decimal(d.get("iof")),
        para_decimal(d.get("premio_total")),
        _int_ou_none(d.get("forma_pagamento_id")),
        para_decimal(d.get("comissao_percentual")),
        para_decimal(d.get("comissao_valor_seguralta_receber")),
        para_decimal(d.get("comissao_valor_plenus_receber")),
        para_decimal(d.get("comissao_valor_seguralta_recebido")),
        para_decimal(d.get("comissao_valor_plenus_recebido")),
        (d.get("data_seguralta_recebido") or "").strip() or None,
        (d.get("data_plenus_recebido") or "").strip() or None,
        _int_ou_none(d.get("recibo_id")),
        _sim_nao(d.get("comissao_parcelada")),
        _sim_nao(d.get("comissao_cocorretagem")),
        (d.get("data_deposito_cc") or "").strip() or None,
        para_decimal(d.get("previsto_relatorio_seguralta")),
        para_decimal(d.get("recebido_relatorio_seguralta")),
        para_decimal(d.get("previsto_relatorio_plenus")),
        para_decimal(d.get("recebido_relatorio_plenus")),
        _sim_nao(d.get("lancado_quiver")),
        (d.get("link_onedrive") or "").strip() or None,
        (d.get("observacao") or "").strip() or None,
    ]


def _inserir_servico_parcelas(con, servico_id, parcelas):
    hoje = date.today().isoformat()
    for p in parcelas or []:
        paga = 1 if p.get("paga") in (1, "1", True, "sim", "on") else 0
        pago_em = (p.get("pago_em") or "").strip() or (hoje if paga else None)
        aviso = 1 if p.get("aviso_ok") in (1, "1", True, "sim", "on") else 0
        aviso_em = (p.get("aviso_ok_em") or "").strip() or (hoje if aviso else None)
        enviado = 1 if p.get("enviado") in (1, "1", True, "sim", "on") else 0
        enviado_em = (p.get("enviado_em") or "").strip() or (hoje if enviado else None)
        con.execute(
            "INSERT INTO servico_parcela "
            "(servico_id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em, "
            " enviado, enviado_em) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (servico_id, p.get("identificacao"), p.get("data"), p.get("valor"),
             paga, pago_em, aviso, aviso_em, enviado, enviado_em))


def _inserir_servico_comissoes(con, servico_id, linhas):
    for i, c in enumerate(linhas or []):
        con.execute(
            "INSERT INTO servico_comissao "
            "(servico_id, parcela, valor_previsto, valor_recebido, data, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (servico_id, c.get("parcela"), c.get("valor_previsto"),
             c.get("valor_recebido"), c.get("data"), i))


def _inserir_servico_repasses(con, servico_id, linhas):
    for i, r in enumerate(linhas or []):
        con.execute(
            "INSERT INTO servico_repasse "
            "(servico_id, parcela, valor_previsto, valor_recebido, data, recibo_id, "
            " data_deposito_cc, ordem) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (servico_id, r.get("parcela"), r.get("valor_previsto"),
             r.get("valor_recebido"), r.get("data"), _int_ou_none(r.get("recibo_id")),
             r.get("data_deposito_cc"), i))


_SQL_SERVICO_SEL = """
SELECT sv.*, ap.numero_apolice AS ap_numero, tsa.nome AS ap_tipo_seguro_nome,
       c.nome AS cliente_nome, c.tipo_pessoa AS cliente_tipo_pessoa,
       s.nome AS seguradora_nome, ts.nome AS tipo_servico_nome,
       sa.nome AS status_apolice_nome, f.nome AS forma_pagamento_nome,
       (SELECT p.data FROM servico_parcela p
          WHERE p.servico_id = sv.id AND COALESCE(p.paga, 0) = 0 AND p.data IS NOT NULL
          ORDER BY p.data LIMIT 1) AS proxima_parcela_data,
       (SELECT COUNT(*) FROM servico_parcela p WHERE p.servico_id = sv.id) AS total_parcelas
  FROM servico sv
  LEFT JOIN apolice ap        ON ap.id = sv.apolice_id
  LEFT JOIN tipo_seguro tsa   ON tsa.id = ap.tipo_seguro_id
  LEFT JOIN cliente c         ON c.id = sv.cliente_id
  LEFT JOIN seguradora s      ON s.id = sv.seguradora_id
  LEFT JOIN tipo_servico ts   ON ts.id = sv.tipo_servico_id
  LEFT JOIN status_apolice sa ON sa.id = sv.status_apolice_id
  LEFT JOIN forma_pagamento f ON f.id = sv.forma_pagamento_id
"""


def _linha_servico(l):
    """O número da apólice do serviço é o da apólice vinculada (a coluna antiga
    servico.numero_apolice ficou da 1ª versão e não é mais usada)."""
    d = dict(l)
    d["numero_apolice"] = d.pop("ap_numero", None)
    d["apolice_tipo_seguro_nome"] = d.pop("ap_tipo_seguro_nome", None)
    return d


def listar_servicos(cliente_id=None, busca=None, quiver=None, tipo_servico_id=None,
                    seguradora_id=None, status_apolice_id=None, apolice_id=None):
    sql, params, filtros = _SQL_SERVICO_SEL, [], []
    for coluna, valor in (("sv.cliente_id", cliente_id), ("sv.apolice_id", apolice_id),
                          ("sv.tipo_servico_id", tipo_servico_id),
                          ("sv.seguradora_id", seguradora_id),
                          ("sv.status_apolice_id", status_apolice_id)):
        if valor:
            filtros.append(f"{coluna} = %s")
            params.append(valor)
    if quiver in (0, 1, True, False):
        filtros.append("COALESCE(sv.lancado_quiver, 0) = %s")
        params.append(1 if quiver in (1, True) else 0)
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY sv.criado_em DESC, sv.id DESC"
    with conexao() as con:
        linhas = [_linha_servico(l) for l in con.execute(sql, params).fetchall()]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [l for l in linhas
                  if alvo in _sem_acento_minusculo(l.get("cliente_nome") or "")
                  or alvo in _sem_acento_minusculo(l.get("numero_apolice") or "")
                  or alvo in _sem_acento_minusculo(l.get("numero_proposta") or "")]
    return linhas


def obter_servico(servico_id):
    with conexao() as con:
        l = con.execute(_SQL_SERVICO_SEL + " WHERE sv.id = %s", (servico_id,)).fetchone()
        if not l:
            return None
        sv = _linha_servico(l)
        if sv.get("recibo_id"):
            rec = con.execute("SELECT numero FROM recibo WHERE id = %s", (sv["recibo_id"],)).fetchone()
            sv["recibo_numero"] = rec["numero"] if rec else None
        sv["parcelas"] = [dict(p) for p in con.execute(
            "SELECT id, identificacao, data, valor, paga, pago_em, aviso_ok, aviso_ok_em, "
            "       enviado, enviado_em "
            "FROM servico_parcela WHERE servico_id = %s ORDER BY COALESCE(data, ''), id",
            (servico_id,)).fetchall()]
        sv["comissoes"] = [dict(x) for x in con.execute(
            "SELECT id, parcela, valor_previsto, valor_recebido, data "
            "FROM servico_comissao WHERE servico_id = %s ORDER BY ordem, id",
            (servico_id,)).fetchall()]
        sv["repasses"] = [dict(x) for x in con.execute(
            "SELECT r.id, r.parcela, r.valor_previsto, r.valor_recebido, r.data, r.recibo_id, "
            "       r.data_deposito_cc, rec.numero AS recibo_numero "
            "FROM servico_repasse r LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            "WHERE r.servico_id = %s ORDER BY r.ordem, r.id",
            (servico_id,)).fetchall()]
        return sv


def criar_servico(dados, parcelas=None, comissoes=None, repasses=None):
    with conexao() as con:
        marc = ", ".join("%s" for _ in _COLS_SERVICO)
        cur = con.execute(
            f"INSERT INTO servico ({', '.join(_COLS_SERVICO)}) VALUES ({marc})",
            _valores_servico(dados))
        novo_id = cur.lastrowid
        _inserir_servico_parcelas(con, novo_id, parcelas)
        _inserir_servico_comissoes(con, novo_id, comissoes)
        _inserir_servico_repasses(con, novo_id, repasses)
    fazer_backup()
    return novo_id


def atualizar_servico(servico_id, dados, parcelas=None, comissoes=None, repasses=None):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_SERVICO)
        con.execute(
            f"UPDATE servico SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_servico(dados) + [servico_id])
        _sincronizar_parcelas(con, "servico_parcela", "servico_id", servico_id, parcelas)
        for tab in ("servico_comissao", "servico_repasse"):
            con.execute(f"DELETE FROM {tab} WHERE servico_id = %s", (servico_id,))
        _inserir_servico_comissoes(con, servico_id, comissoes)
        _inserir_servico_repasses(con, servico_id, repasses)
    fazer_backup()


def excluir_servico(servico_id):
    with conexao() as con:
        con.execute("DELETE FROM servico WHERE id = %s", (servico_id,))
    fazer_backup()


def contar_servicos_do_cliente(cliente_id):
    with conexao() as con:
        return _um(con.execute("SELECT COUNT(*) FROM servico WHERE cliente_id = %s", (cliente_id,)))


def contar_servicos_por_apolice(apolice_id):
    with conexao() as con:
        return _um(con.execute("SELECT COUNT(*) FROM servico WHERE apolice_id = %s", (apolice_id,)))


def salvar_comissoes_repasses_servico(servico_id, comissoes, repasses):
    """Regrava só as tabelas-filhas de comissão parcelada de UM serviço (grade de Entradas)."""
    with conexao() as con:
        con.execute("DELETE FROM servico_comissao WHERE servico_id = %s", (servico_id,))
        _inserir_servico_comissoes(con, servico_id, comissoes)
        con.execute("DELETE FROM servico_repasse WHERE servico_id = %s", (servico_id,))
        _inserir_servico_repasses(con, servico_id, repasses)
        con.execute("UPDATE servico SET atualizado_em = NOW() WHERE id = %s", (servico_id,))
    fazer_backup()


def salvar_comissao_servico(servico_id, valores):
    """Grava só a comissão (valores achatados) de um serviço, a partir do bloco
    editável de Entradas. Mesmas chaves de `salvar_comissao_unica`."""
    with conexao() as con:
        con.execute(
            "UPDATE servico SET "
            "  comissao_valor_seguralta_receber = %s, comissao_valor_seguralta_recebido = %s, "
            "  comissao_valor_plenus_receber = %s, comissao_valor_plenus_recebido = %s, "
            "  data_seguralta_recebido = %s, data_plenus_recebido = %s, "
            "  recibo_id = %s, data_deposito_cc = %s, atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             _int_ou_none(valores.get("recibo_id")),
             (valores.get("data_deposito_cc") or None),
             servico_id),
        )
    fazer_backup()


def obter_apolice_basico(apolice_id):
    """id, número, cliente e seguradora — sem carregar parcelas/comissões."""
    with conexao() as con:
        l = con.execute(
            "SELECT a.id, a.numero_apolice, a.cliente_id, c.nome AS cliente_nome, "
            "       s.nome AS seguradora_nome "
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
            "  recibo_id = %s, "
            "  data_deposito_cc = %s, "
            "  atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             _int_ou_none(valores.get("recibo_id")),
             (valores.get("data_deposito_cc") or None),
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
            "  recibo_id = %s, data_deposito_cc = %s, atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             _int_ou_none(valores.get("recibo_id")),
             (valores.get("data_deposito_cc") or None),
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
            "  plenus_conferido_banco = %s, data_deposito_cc = %s, atualizado_em = NOW() "
            "WHERE id = %s",
            (valores.get("comissao_valor_seguralta_receber"),
             valores.get("comissao_valor_seguralta_recebido"),
             valores.get("comissao_valor_plenus_receber"),
             valores.get("comissao_valor_plenus_recebido"),
             (valores.get("data_seguralta_recebido") or None),
             (valores.get("data_plenus_recebido") or None),
             1 if valores.get("plenus_conferido_banco") in (1, "1", True, "sim", "on") else 0,
             (valores.get("data_deposito_cc") or None),
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
            "consorcio": "notificacao_consorcio_boleto",
            "servico": "notificacao_servico_parcela"}.get(origem, "notificacao_parcela")


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

_SQL_PARCELAS_BOLETO_SERV = """
SELECT 'servico' AS origem, p.id AS parcela_id, NULL AS endosso_id, NULL AS endosso_numero,
       NULL AS consorcio_id, NULL AS consorcio_grupo, NULL AS consorcio_cota, NULL AS boleto_status,
       p.identificacao, p.data, p.valor, p.aviso_ok, p.enviado, p.enviado_em,
       sv.apolice_id, (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, sv.vigencia_inicio, sv.vigencia_fim,
       sv.id AS servico_id,
       c.nome AS cliente_nome, s.nome AS seguradora_nome, ts.nome AS tipo_seguro_nome,
       f.nome AS forma_pagamento_nome
  FROM servico_parcela p
  JOIN servico sv           ON sv.id = p.servico_id
  LEFT JOIN cliente c       ON c.id = sv.cliente_id
  LEFT JOIN seguradora s    ON s.id = sv.seguradora_id
  LEFT JOIN tipo_servico ts ON ts.id = sv.tipo_servico_id
  JOIN forma_pagamento f    ON f.id = sv.forma_pagamento_id
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
    """Boletos com data e não pagos — de apólices, endossos, serviços E consórcios."""
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO).fetchall()]
        linhas += [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO_END).fetchall()]
        linhas += [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO_SERV).fetchall()]
        linhas += [dict(l) for l in con.execute(_SQL_PARCELAS_BOLETO_CONS).fetchall()]
    linhas.sort(key=lambda l: l.get("data") or "")
    return linhas


def boletos_consorcio_nao_enviados():
    """Boletos de consórcio com status 'a_enviar' (a janela de aviso é decidida em avisos.py)."""
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

_COLS_SAIDA = ("descricao", "categoria_id", "forma_pagamento_id", "conta_origem_id", "valor",
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
        _para_int(dados.get("conta_origem_id")),
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
        "conta_origem_id": s.get("conta_origem_id"),
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
                  forma_pagamento_id=None, conta_origem_id=None, fixo=None,
                  data_ini=None, data_fim=None, base_data="vencimento"):
    """`data_ini`/`data_fim` (ISO, inclusivo) recortam por `base_data`:
    'vencimento' → `data_vencimento`; 'pagamento' → `data_pagamento` (exclui não pagas)."""
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT s.id, s.descricao, s.categoria_id, s.forma_pagamento_id, s.conta_origem_id, "
            "       s.valor, "
            "       s.data_vencimento, s.data_pagamento, s.numero_parcela, s.fixo_mensal, "
            "       s.serie_id, s.criado_em, s.atualizado_em, "
            "       c.nome AS categoria, fp.nome AS forma_pagamento, co.nome AS conta_origem "
            "FROM saida s "
            "LEFT JOIN categoria_saida c ON c.id = s.categoria_id "
            "LEFT JOIN forma_pagamento fp ON fp.id = s.forma_pagamento_id "
            "LEFT JOIN conta_origem co ON co.id = s.conta_origem_id "
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
    if conta_origem_id:
        linhas = [s for s in linhas if s.get("conta_origem_id") == int(conta_origem_id)]
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


def contas_origem():
    """Lista o cadastro de contas de origem ([{id, nome}])."""
    return listar_simples("conta_origem")


def descricoes_saida():
    """Descrições distintas já cadastradas em `saida` (p/ o autocomplete da busca)."""
    with conexao() as con:
        return [r["descricao"] for r in con.execute(
            "SELECT DISTINCT descricao FROM saida "
            "WHERE descricao IS NOT NULL AND TRIM(descricao) <> '' "
            "ORDER BY descricao"
        ).fetchall()]


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


# ---------- entradas simples (lançamento avulso, fora das comissões) ----------

_COLS_ENTRADA_SIMPLES = ("descricao", "forma_pagamento_id", "conta_origem_id",
                         "conta_destino_id", "data", "valor", "observacao")


def _valores_entrada_simples(dados):
    return [
        (dados.get("descricao") or "").strip() or None,
        _int_ou_none(dados.get("forma_pagamento_id")),
        _int_ou_none(dados.get("conta_origem_id")),
        _int_ou_none(dados.get("conta_destino_id")),
        (dados.get("data") or "").strip() or None,
        para_decimal(dados.get("valor")),
        (dados.get("observacao") or "").strip() or None,
    ]


def obter_entrada_simples(entrada_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM entrada_simples WHERE id = %s", (entrada_id,)).fetchone()
        return dict(l) if l else None


def criar_entrada_simples(dados):
    with conexao() as con:
        marcadores = ", ".join("%s" for _ in _COLS_ENTRADA_SIMPLES)
        cur = con.execute(
            f"INSERT INTO entrada_simples ({', '.join(_COLS_ENTRADA_SIMPLES)}) VALUES ({marcadores})",
            _valores_entrada_simples(dados),
        )
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def atualizar_entrada_simples(entrada_id, dados):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_ENTRADA_SIMPLES)
        con.execute(
            f"UPDATE entrada_simples SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_entrada_simples(dados) + [entrada_id],
        )
    fazer_backup()


def excluir_entrada_simples(entrada_id):
    with conexao() as con:
        con.execute("DELETE FROM entrada_simples WHERE id = %s", (entrada_id,))
    fazer_backup()


def listar_entradas_simples(mes=None, busca=None, forma_pagamento_id=None, conta_origem_id=None,
                            conta_destino_id=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT e.*, fp.nome AS forma_pagamento, co.nome AS conta_origem, "
            "       cd.nome AS conta_destino "
            "  FROM entrada_simples e "
            "  LEFT JOIN forma_pagamento fp ON fp.id = e.forma_pagamento_id "
            "  LEFT JOIN conta_origem co   ON co.id = e.conta_origem_id "
            "  LEFT JOIN conta_origem cd   ON cd.id = e.conta_destino_id "
            " ORDER BY COALESCE(e.data, ''), e.id"
        ).fetchall()]
    if mes:
        linhas = [l for l in linhas if (l.get("data") or "")[5:7] == f"{int(mes):02d}"]
    if forma_pagamento_id:
        linhas = [l for l in linhas if l.get("forma_pagamento_id") == forma_pagamento_id]
    if conta_origem_id:
        linhas = [l for l in linhas if l.get("conta_origem_id") == conta_origem_id]
    if conta_destino_id:
        linhas = [l for l in linhas if l.get("conta_destino_id") == conta_destino_id]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [l for l in linhas if alvo in _sem_acento_minusculo(l.get("descricao") or "")]
    return linhas


# ---------- notas fiscais (+ recibos) ----------

_COLS_NOTA_FISCAL = ("numero", "valor", "data_emissao", "data_pagamento", "data_depositado",
                     "observacao")


def _valores_nota_fiscal(dados):
    return [
        (dados.get("numero") or "").strip() or None,
        para_decimal(dados.get("valor")),
        (dados.get("data_emissao") or "").strip() or None,
        (dados.get("data_pagamento") or "").strip() or None,
        (dados.get("data_depositado") or "").strip() or None,
        (dados.get("observacao") or "").strip() or None,
    ]


def _aplicar_recibos_da_nota_fiscal(con, nota_fiscal_id, recibo_ids):
    """Vincula exatamente os recibos de `recibo_ids` a esta nota fiscal (desvincula os
    que estavam e nao vieram mais). O campo "valor" NAO e mexido aqui - ele e sugerido
    pelo JS (soma dos recibos marcados) mas continua editavel, igual ao premio_total
    da apolice."""
    ids = {int(x) for x in (recibo_ids or []) if str(x).strip().isdigit()}
    con.execute(
        "UPDATE recibo SET nota_fiscal_id = NULL, atualizado_em = NOW() "
        "WHERE nota_fiscal_id = %s", (nota_fiscal_id,))
    if ids:
        marcadores = ", ".join("%s" for _ in ids)
        con.execute(
            f"UPDATE recibo SET nota_fiscal_id = %s, atualizado_em = NOW() "
            f"WHERE id IN ({marcadores})",
            [nota_fiscal_id, *ids],
        )


def obter_nota_fiscal(nota_fiscal_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM nota_fiscal WHERE id = %s", (nota_fiscal_id,)).fetchone()
        if not l:
            return None
        nf = dict(l)
        # recibos vinculados: so leitura aqui - cada recibo e cadastrado/editado na
        # tela dele mesmo (existe independente da nota fiscal, ver secao mais abaixo)
        nf["recibos"] = [dict(r) for r in con.execute(
            "SELECT id, numero, data, valor_bruto, aliquota, valor_liquido, data_envio "
            "FROM recibo WHERE nota_fiscal_id = %s ORDER BY COALESCE(data, ''), id",
            (nota_fiscal_id,),
        ).fetchall()]
        return nf


def criar_nota_fiscal(dados, recibo_ids=None):
    with conexao() as con:
        marcadores = ", ".join("%s" for _ in _COLS_NOTA_FISCAL)
        cur = con.execute(
            f"INSERT INTO nota_fiscal ({', '.join(_COLS_NOTA_FISCAL)}) VALUES ({marcadores})",
            _valores_nota_fiscal(dados),
        )
        novo_id = cur.lastrowid
        _aplicar_recibos_da_nota_fiscal(con, novo_id, recibo_ids)
    fazer_backup()
    return novo_id


def atualizar_nota_fiscal(nota_fiscal_id, dados, recibo_ids=None):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_NOTA_FISCAL)
        con.execute(
            f"UPDATE nota_fiscal SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_nota_fiscal(dados) + [nota_fiscal_id],
        )
        _aplicar_recibos_da_nota_fiscal(con, nota_fiscal_id, recibo_ids)
    fazer_backup()


def excluir_nota_fiscal(nota_fiscal_id):
    # os recibos vinculados NAO somem - so ficam sem nota fiscal (ON DELETE SET NULL)
    with conexao() as con:
        con.execute("DELETE FROM nota_fiscal WHERE id = %s", (nota_fiscal_id,))
    fazer_backup()


def notas_fiscais_para_select():
    """[{id, numero}] pro <select> de vinculo no formulario do recibo."""
    with conexao() as con:
        return [dict(l) for l in con.execute(
            "SELECT id, numero FROM nota_fiscal ORDER BY COALESCE(data_emissao, '') DESC, id DESC"
        ).fetchall()]


def recibos_selecionaveis(nota_fiscal_id=None):
    """Recibos sem nota fiscal OU ja vinculados a `nota_fiscal_id` - pro checklist de
    "recibos associados" do formulario da nota fiscal. Um recibo vinculado a OUTRA
    nota fiscal nao aparece (evita "roubar" o recibo de outra nota sem querer)."""
    with conexao() as con:
        if nota_fiscal_id:
            linhas = con.execute(
                "SELECT * FROM recibo WHERE nota_fiscal_id IS NULL OR nota_fiscal_id = %s "
                "ORDER BY COALESCE(data, ''), id", (nota_fiscal_id,)).fetchall()
        else:
            linhas = con.execute(
                "SELECT * FROM recibo WHERE nota_fiscal_id IS NULL "
                "ORDER BY COALESCE(data, ''), id").fetchall()
        return [dict(l) for l in linhas]


def _status_nota_fiscal(nf):
    if nf.get("data_depositado"):
        return "depositada"
    if nf.get("data_pagamento"):
        return "paga"
    return "aberta"


def listar_notas_fiscais(busca=None, status=None, mes_emissao=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT nf.*, "
            "       (SELECT COUNT(*) FROM recibo r WHERE r.nota_fiscal_id = nf.id) AS qtd_recibos, "
            "       (SELECT COALESCE(SUM(r.valor_liquido), 0) FROM recibo r "
            "          WHERE r.nota_fiscal_id = nf.id) AS soma_recibos_liquido "
            "FROM nota_fiscal nf "
            "ORDER BY COALESCE(nf.data_emissao, ''), nf.id"
        ).fetchall()]
    for nf in linhas:
        nf["status"] = _status_nota_fiscal(nf)

    if mes_emissao:
        linhas = [nf for nf in linhas
                 if (nf.get("data_emissao") or "")[5:7] == f"{int(mes_emissao):02d}"]
    if status in ("aberta", "paga", "depositada"):
        linhas = [nf for nf in linhas if nf["status"] == status]
    termo = (busca or "").strip()
    if termo:
        alvo = _sem_acento_minusculo(termo)
        linhas = [nf for nf in linhas if alvo in _sem_acento_minusculo(nf.get("numero") or "")]
    return linhas


# ---------- recibos (cadastrados/enviados antes de existir a nota fiscal;
#             o vinculo com ela e opcional e' feito depois, editando o recibo) ----------

_COLS_RECIBO = ("nota_fiscal_id", "numero", "data", "valor_bruto", "aliquota",
               "valor_liquido", "data_envio", "observacao")


def _valores_recibo(dados):
    return [
        _int_ou_none(dados.get("nota_fiscal_id")),
        (dados.get("numero") or "").strip() or None,
        (dados.get("data") or "").strip() or None,
        para_decimal(dados.get("valor_bruto")),
        para_decimal(dados.get("aliquota")),
        para_decimal(dados.get("valor_liquido")),
        (dados.get("data_envio") or "").strip() or None,
        (dados.get("observacao") or "").strip() or None,
    ]


def obter_recibo(recibo_id):
    with conexao() as con:
        l = con.execute("SELECT * FROM recibo WHERE id = %s", (recibo_id,)).fetchone()
        return dict(l) if l else None


def criar_recibo(dados):
    with conexao() as con:
        marcadores = ", ".join("%s" for _ in _COLS_RECIBO)
        cur = con.execute(
            f"INSERT INTO recibo ({', '.join(_COLS_RECIBO)}) VALUES ({marcadores})",
            _valores_recibo(dados),
        )
        novo_id = cur.lastrowid
    fazer_backup()
    return novo_id


def atualizar_recibo(recibo_id, dados):
    with conexao() as con:
        atrib = ", ".join(f"{c} = %s" for c in _COLS_RECIBO)
        con.execute(
            f"UPDATE recibo SET {atrib}, atualizado_em = NOW() WHERE id = %s",
            _valores_recibo(dados) + [recibo_id],
        )
    fazer_backup()


def excluir_recibo(recibo_id):
    with conexao() as con:
        con.execute("DELETE FROM recibo WHERE id = %s", (recibo_id,))
    fazer_backup()


def _status_recibo(r):
    return "enviado" if r.get("data_envio") else "pendente"


def listar_recibos(busca=None, status=None, vinculado=None, mes=None):
    with conexao() as con:
        linhas = [dict(l) for l in con.execute(
            "SELECT r.*, nf.numero AS nota_fiscal_numero "
            "FROM recibo r "
            "LEFT JOIN nota_fiscal nf ON nf.id = r.nota_fiscal_id "
            "ORDER BY COALESCE(r.data, ''), r.id"
        ).fetchall()]
    for r in linhas:
        r["status"] = _status_recibo(r)

    if mes:
        linhas = [r for r in linhas if (r.get("data") or "")[5:7] == f"{int(mes):02d}"]
    if status in ("enviado", "pendente"):
        linhas = [r for r in linhas if r["status"] == status]
    if vinculado in ("sim", "nao"):
        alvo = vinculado == "sim"
        linhas = [r for r in linhas if bool(r.get("nota_fiscal_id")) == alvo]
    termo = (busca or "").strip()
    if termo:
        alvo_txt = _sem_acento_minusculo(termo)
        linhas = [r for r in linhas if alvo_txt in _sem_acento_minusculo(r.get("numero") or "")]
    return linhas


# ---------- vinculo entre recibo e parcela de comissao ----------
# o recibo e cadastrado (e enviado) antes de existir a nota fiscal; da mesma forma,
# ele e' o dono do vinculo com as parcelas de repasse (o que a Plenus recebe da
# corretora) - o campo que antes guardava "conferido no banco" (sim/nao) agora guarda
# o id do recibo associado. So apolice + endosso (parcelada e unica); consorcio fica
# de fora por enquanto.

# origem -> (tabela, coluna do vinculo, tem coluna atualizado_em)
_ORIGENS_REPASSE = {
    "apolice_repasse": ("apolice_repasse", "recibo_id", False),
    "endosso_repasse": ("apolice_endosso_repasse", "recibo_id", False),
    "apolice_unica": ("apolice", "recibo_id", True),
    "endosso_unica": ("apolice_endosso", "recibo_id", True),
    "servico_repasse": ("servico_repasse", "recibo_id", False),
    "servico_unica": ("servico", "recibo_id", True),
    "saida_desconto": ("saida", "recibo_id", True),
}


def parcelas_repasse_por_data(data, recibo_id=None):
    """Parcelas de repasse (comissao que a Plenus recebe) PAGAS na `data` informada,
    excluindo cocorretagem - candidatas a serem vinculadas a um recibo. So mostra as
    que estao sem recibo OU ja vinculadas a `recibo_id` (edicao de um recibo
    existente) - uma parcela vinculada a OUTRO recibo nao aparece."""
    if not (data or "").strip():
        return []
    linhas = []
    with conexao() as con:
        rows = con.execute(
            "SELECT r.id, r.recibo_id, r.valor_recebido, r.parcela, a.numero_apolice, c.nome AS cliente_nome, "
            "       (SELECT COUNT(DISTINCT r2.parcela) FROM apolice_repasse r2 WHERE r2.apolice_id = r.apolice_id) AS total_parcelas "
            "  FROM apolice_repasse r "
            "  JOIN apolice a ON a.id = r.apolice_id "
            "  LEFT JOIN cliente c ON c.id = a.cliente_id "
            " WHERE r.data = %s AND r.valor_recebido IS NOT NULL "
            "   AND COALESCE(a.comissao_cocorretagem, 0) = 0 "
            "   AND (r.recibo_id IS NULL OR r.recibo_id = %s)",
            (data, recibo_id)).fetchall()
        for r in rows:
            linhas.append({"origem": "apolice_repasse", "id": r["id"], "recibo_id": r["recibo_id"],
                           "valor_recebido": r["valor_recebido"], "numero_apolice": r["numero_apolice"],
                           "cliente_nome": r["cliente_nome"],
                           "parcela_rotulo": f"{r['parcela'] or '?'}/{r['total_parcelas']}"})
        rows = con.execute(
            "SELECT a.id, a.recibo_id, a.comissao_valor_plenus_recebido AS valor_recebido, "
            "       a.numero_apolice, c.nome AS cliente_nome "
            "  FROM apolice a LEFT JOIN cliente c ON c.id = a.cliente_id "
            " WHERE a.data_plenus_recebido = %s AND a.comissao_valor_plenus_recebido IS NOT NULL "
            "   AND COALESCE(a.comissao_cocorretagem, 0) = 0 "
            "   AND COALESCE(a.comissao_parcelada, 0) = 0 "
            "   AND (a.recibo_id IS NULL OR a.recibo_id = %s)",
            (data, recibo_id)).fetchall()
        for r in rows:
            linhas.append({"origem": "apolice_unica", "id": r["id"], "recibo_id": r["recibo_id"],
                           "valor_recebido": r["valor_recebido"], "numero_apolice": r["numero_apolice"],
                           "cliente_nome": r["cliente_nome"], "parcela_rotulo": "única"})
        rows = con.execute(
            "SELECT r.id, r.recibo_id, r.valor_recebido, r.parcela, e.numero AS endosso_numero, "
            "       a.numero_apolice, c.nome AS cliente_nome, "
            "       (SELECT COUNT(DISTINCT r2.parcela) FROM apolice_endosso_repasse r2 WHERE r2.endosso_id = r.endosso_id) AS total_parcelas "
            "  FROM apolice_endosso_repasse r "
            "  JOIN apolice_endosso e ON e.id = r.endosso_id "
            "  JOIN apolice a ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c ON c.id = a.cliente_id "
            " WHERE r.data = %s AND r.valor_recebido IS NOT NULL "
            # cocorretagem cai direto na conta corrente (não passa por recibo); a que já
            # estiver vinculada continua aparecendo, pra não sumir de um recibo existente
            "   AND (r.recibo_id = %s OR (r.recibo_id IS NULL "
            "        AND COALESCE(e.comissao_cocorretagem, 0) = 0))",
            (data, recibo_id)).fetchall()
        for r in rows:
            linhas.append({"origem": "endosso_repasse", "id": r["id"], "recibo_id": r["recibo_id"],
                           "valor_recebido": r["valor_recebido"],
                           "numero_apolice": f"{r['numero_apolice']} (endosso {r['endosso_numero']})",
                           "cliente_nome": r["cliente_nome"],
                           "parcela_rotulo": f"{r['parcela'] or '?'}/{r['total_parcelas']}"})
        rows = con.execute(
            "SELECT e.id, e.recibo_id, e.comissao_valor_plenus_recebido AS valor_recebido, "
            "       e.numero AS endosso_numero, a.numero_apolice, c.nome AS cliente_nome "
            "  FROM apolice_endosso e "
            "  JOIN apolice a ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c ON c.id = a.cliente_id "
            " WHERE e.data_plenus_recebido = %s AND e.comissao_valor_plenus_recebido IS NOT NULL "
            "   AND COALESCE(e.comissao_parcelada, 0) = 0 "
            "   AND (e.recibo_id = %s OR (e.recibo_id IS NULL "
            "        AND COALESCE(e.comissao_cocorretagem, 0) = 0))",
            (data, recibo_id)).fetchall()
        for r in rows:
            linhas.append({"origem": "endosso_unica", "id": r["id"], "recibo_id": r["recibo_id"],
                           "valor_recebido": r["valor_recebido"],
                           "numero_apolice": f"{r['numero_apolice']} (endosso {r['endosso_numero']})",
                           "cliente_nome": r["cliente_nome"], "parcela_rotulo": "única"})
        rows = con.execute(
            "SELECT r.id, r.recibo_id, r.valor_recebido, r.parcela, (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, "
            "       ts.nome AS tipo_servico_nome, c.nome AS cliente_nome, "
            "       (SELECT COUNT(DISTINCT r2.parcela) FROM servico_repasse r2 WHERE r2.servico_id = r.servico_id) AS total_parcelas "
            "  FROM servico_repasse r "
            "  JOIN servico sv ON sv.id = r.servico_id "
            "  LEFT JOIN tipo_servico ts ON ts.id = sv.tipo_servico_id "
            "  LEFT JOIN cliente c ON c.id = sv.cliente_id "
            " WHERE r.data = %s AND r.valor_recebido IS NOT NULL "
            "   AND COALESCE(sv.comissao_cocorretagem, 0) = 0 "
            "   AND (r.recibo_id IS NULL OR r.recibo_id = %s)",
            (data, recibo_id)).fetchall()
        for r in rows:
            linhas.append({"origem": "servico_repasse", "id": r["id"], "recibo_id": r["recibo_id"],
                           "valor_recebido": r["valor_recebido"],
                           "numero_apolice": _rotulo_servico(r),
                           "cliente_nome": r["cliente_nome"],
                           "parcela_rotulo": f"{r['parcela'] or '?'}/{r['total_parcelas']}"})
        rows = con.execute(
            "SELECT sv.id, sv.recibo_id, sv.comissao_valor_plenus_recebido AS valor_recebido, "
            "       (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, ts.nome AS tipo_servico_nome, c.nome AS cliente_nome "
            "  FROM servico sv "
            "  LEFT JOIN tipo_servico ts ON ts.id = sv.tipo_servico_id "
            "  LEFT JOIN cliente c ON c.id = sv.cliente_id "
            " WHERE sv.data_plenus_recebido = %s AND sv.comissao_valor_plenus_recebido IS NOT NULL "
            "   AND COALESCE(sv.comissao_cocorretagem, 0) = 0 "
            "   AND COALESCE(sv.comissao_parcelada, 0) = 0 "
            "   AND (sv.recibo_id IS NULL OR sv.recibo_id = %s)",
            (data, recibo_id)).fetchall()
        for r in rows:
            linhas.append({"origem": "servico_unica", "id": r["id"], "recibo_id": r["recibo_id"],
                           "valor_recebido": r["valor_recebido"],
                           "numero_apolice": _rotulo_servico(r),
                           "cliente_nome": r["cliente_nome"], "parcela_rotulo": "única"})
    return linhas


def _rotulo_servico(r):
    """'<nº da apólice> (serviço <tipo>)' — como o serviço aparece nas listas de comissão."""
    tipo = (r.get("tipo_servico_nome") or "").strip()
    return f"{r.get('numero_apolice') or '—'} (serviço{' ' + tipo if tipo else ''})"


def saidas_desconto_por_data(data, recibo_id=None):
    """Saidas com conta de origem 'Recibo' (descontadas direto do recibo, ex.: cadastro
    de proposta - em vez de sair de uma conta nossa) vencendo na `data` informada -
    candidatas a serem abatidas de um recibo. Mesma logica de
    parcelas_repasse_por_data: so mostra as sem recibo OU ja vinculadas a `recibo_id`."""
    if not (data or "").strip():
        return []
    with conexao() as con:
        rows = con.execute(
            "SELECT s.id, s.recibo_id, s.descricao, s.valor "
            "  FROM saida s "
            "  JOIN conta_origem co ON co.id = s.conta_origem_id "
            " WHERE co.nome = 'Recibo' AND s.data_vencimento = %s "
            "   AND (s.recibo_id IS NULL OR s.recibo_id = %s)",
            (data, recibo_id)).fetchall()
    return [{"origem": "saida_desconto", "id": r["id"], "recibo_id": r["recibo_id"],
             "valor": r["valor"], "descricao": r["descricao"]} for r in rows]


def aplicar_parcelas_do_recibo(recibo_id, refs):
    """`refs` = ["origem:id", ...] vindos do checklist do formulario do recibo.
    Desvincula tudo que estava associado a este recibo e nao veio mais marcado, e
    vincula exatamente as linhas de `refs`."""
    alvos = {}
    for ref in (refs or []):
        origem, _, rid = (ref or "").partition(":")
        if origem in _ORIGENS_REPASSE and rid.isdigit():
            alvos.setdefault(origem, set()).add(int(rid))
    with conexao() as con:
        for origem, (tabela, coluna, tem_timestamp) in _ORIGENS_REPASSE.items():
            ids = alvos.get(origem, set())
            sufixo = ", atualizado_em = NOW()" if tem_timestamp else ""
            con.execute(f"UPDATE {tabela} SET {coluna} = NULL{sufixo} WHERE {coluna} = %s",
                       (recibo_id,))
            if ids:
                marcadores = ", ".join("%s" for _ in ids)
                con.execute(
                    f"UPDATE {tabela} SET {coluna} = %s{sufixo} WHERE id IN ({marcadores})",
                    [recibo_id, *ids])
    fazer_backup()


# ---------- entradas (contas a receber = repasses de comissão) ----------

# ---------- conta corrente (extrato só-leitura, montado do que já está lançado) ----------

def extrato_conta_corrente():
    """Extrato da conta corrente PJ da Plenus — não tem lançamento próprio, é
    inteiramente derivado do que já está lançado no sistema:

    * saídas: `saida` com conta de origem "PESSOA JURÍDICA", já PAGAS
      (data_pagamento preenchida) — data do movimento = data_pagamento;
    * entradas — três fluxos que resultam em dinheiro na conta da Plenus:
        - entrada simples: `entrada_simples` com conta de DESTINO "PESSOA
          JURÍDICA" e `data` preenchida — lançamento avulso (fora de
          comissão); "conta de origem" é de onde veio o dinheiro (pode ser
          de fora, ex. pessoa física), "conta de destino" é qual conta NOSSA
          recebeu — é essa que importa pro extrato;
        - cocorretagem: a Plenus recebe direto da seguradora, sem passar por
          recibo/NF (ver data_deposito_cc) — parcelas E repasse único de
          apólice/endosso/consórcio, só quando cocorretagem = 1. Na vida real
          a seguradora deposita tudo que venceu naquele dia numa TACADA SÓ,
          então as linhas de cocorretagem são agrupadas por (data, seguradora)
          e somadas — uma linha por depósito real, não uma por apólice;
        - fluxo normal (recibo → nota fiscal): quando a NOTA FISCAL é paga, isso
          é o repasse da Seguralta caindo na conta da Plenus — data do movimento
          = data_depositado (quando o dinheiro realmente entra na conta), caindo
          pra data_pagamento se ainda não tiver o depósito registrado.

    Devolve TODA a história (sem filtro de período), ordenada por data — quem
    chama decide o recorte de exibição e calcula o saldo corrido em cima da
    lista inteira. Cada linha: {data, tipo('entrada'|'saida'), origem,
    descricao, valor(sempre positivo)}."""
    linhas = []
    coco_grupos = {}   # (data, seguradora_nome) -> {"valor": soma, "itens": [descricao, ...]}

    def _junta_coco(data, seguradora_nome, valor, item):
        chave = (data, seguradora_nome or "Sem seguradora")
        g = coco_grupos.setdefault(chave, {"valor": 0.0, "itens": []})
        g["valor"] += float(valor or 0)
        g["itens"].append(item)

    with conexao() as con:
        for r in con.execute(
            "SELECT s.data_pagamento AS data, s.valor, s.descricao, "
            "       cat.nome AS categoria_nome "
            "  FROM saida s "
            "  JOIN conta_origem co ON co.id = s.conta_origem_id "
            "  LEFT JOIN categoria_saida cat ON cat.id = s.categoria_id "
            " WHERE co.nome = 'PESSOA JURÍDICA' AND s.data_pagamento IS NOT NULL"
        ).fetchall():
            desc = r["descricao"] or r["categoria_nome"] or "Saída"
            linhas.append({"data": r["data"], "tipo": "saida", "origem": "saida",
                           "descricao": desc, "valor": float(r["valor"] or 0)})

        for r in con.execute(
            "SELECT e.data, e.valor, e.descricao "
            "  FROM entrada_simples e "
            "  JOIN conta_origem cd ON cd.id = e.conta_destino_id "
            " WHERE cd.nome = 'PESSOA JURÍDICA' AND e.data IS NOT NULL"
        ).fetchall():
            linhas.append({"data": r["data"], "tipo": "entrada", "origem": "entrada_simples",
                           "descricao": r["descricao"] or "Entrada", "valor": float(r["valor"] or 0)})

        for r in con.execute(
            "SELECT r.data_deposito_cc AS data, r.valor_recebido AS valor, r.parcela, "
            "       a.numero_apolice, c.nome AS cliente_nome, sg.nome AS seguradora_nome "
            "  FROM apolice_repasse r "
            "  JOIN apolice a ON a.id = r.apolice_id "
            "  LEFT JOIN cliente c ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " WHERE a.comissao_cocorretagem = 1 "
            "   AND r.valor_recebido IS NOT NULL AND r.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = (f"{r['cliente_nome'] or 'sem cliente'} — apólice {r['numero_apolice'] or '—'} "
                    f"(parcela {r['parcela'] or '?'})")
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT a.data_deposito_cc AS data, a.comissao_valor_plenus_recebido AS valor, "
            "       a.numero_apolice, c.nome AS cliente_nome, sg.nome AS seguradora_nome "
            "  FROM apolice a LEFT JOIN cliente c ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " WHERE a.comissao_cocorretagem = 1 AND COALESCE(a.comissao_parcelada, 0) = 0 "
            "   AND a.comissao_valor_plenus_recebido IS NOT NULL AND a.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = f"{r['cliente_nome'] or 'sem cliente'} — apólice {r['numero_apolice'] or '—'}"
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT r.data_deposito_cc AS data, r.valor_recebido AS valor, r.parcela, "
            "       e.numero AS endosso_numero, a.numero_apolice, c.nome AS cliente_nome, "
            "       sg.nome AS seguradora_nome "
            "  FROM apolice_endosso_repasse r "
            "  JOIN apolice_endosso e ON e.id = r.endosso_id "
            "  JOIN apolice a ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " WHERE e.comissao_cocorretagem = 1 "
            "   AND r.valor_recebido IS NOT NULL AND r.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = (f"{r['cliente_nome'] or 'sem cliente'} — apólice {r['numero_apolice'] or '—'} "
                    f"endosso {r['endosso_numero'] or '—'} (parcela {r['parcela'] or '?'})")
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT e.data_deposito_cc AS data, e.comissao_valor_plenus_recebido AS valor, "
            "       e.numero AS endosso_numero, a.numero_apolice, c.nome AS cliente_nome, "
            "       sg.nome AS seguradora_nome "
            "  FROM apolice_endosso e "
            "  JOIN apolice a ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c ON c.id = a.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            " WHERE e.comissao_cocorretagem = 1 AND COALESCE(e.comissao_parcelada, 0) = 0 "
            "   AND e.comissao_valor_plenus_recebido IS NOT NULL AND e.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = (f"{r['cliente_nome'] or 'sem cliente'} — apólice {r['numero_apolice'] or '—'} "
                    f"endosso {r['endosso_numero'] or '—'}")
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT r.data_deposito_cc AS data, r.valor_recebido AS valor, r.parcela, "
            "       co.numero_grupo, co.numero_cota, c.nome AS cliente_nome, sg.nome AS seguradora_nome "
            "  FROM consorcio_repasse r "
            "  JOIN consorcio co ON co.id = r.consorcio_id "
            "  LEFT JOIN cliente c ON c.id = co.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = co.seguradora_id "
            " WHERE co.comissao_cocorretagem = 1 "
            "   AND r.valor_recebido IS NOT NULL AND r.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = (f"{r['cliente_nome'] or 'sem cliente'} — consórcio grupo {r['numero_grupo'] or '—'} "
                    f"(parcela {r['parcela'] or '?'})")
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT co.data_deposito_cc AS data, co.comissao_valor_plenus_recebido AS valor, "
            "       co.numero_grupo, co.numero_cota, c.nome AS cliente_nome, sg.nome AS seguradora_nome "
            "  FROM consorcio co LEFT JOIN cliente c ON c.id = co.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = co.seguradora_id "
            " WHERE co.comissao_cocorretagem = 1 AND COALESCE(co.comissao_parcelada, 0) = 0 "
            "   AND co.comissao_valor_plenus_recebido IS NOT NULL AND co.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = f"{r['cliente_nome'] or 'sem cliente'} — consórcio grupo {r['numero_grupo'] or '—'}"
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT r.data_deposito_cc AS data, r.valor_recebido AS valor, r.parcela, "
            "       (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, c.nome AS cliente_nome, sg.nome AS seguradora_nome "
            "  FROM servico_repasse r "
            "  JOIN servico sv ON sv.id = r.servico_id "
            "  LEFT JOIN cliente c ON c.id = sv.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = sv.seguradora_id "
            " WHERE sv.comissao_cocorretagem = 1 "
            "   AND r.valor_recebido IS NOT NULL AND r.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = (f"{r['cliente_nome'] or 'sem cliente'} — serviço {r['numero_apolice'] or '—'} "
                    f"(parcela {r['parcela'] or '?'})")
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for r in con.execute(
            "SELECT sv.data_deposito_cc AS data, sv.comissao_valor_plenus_recebido AS valor, "
            "       (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, c.nome AS cliente_nome, sg.nome AS seguradora_nome "
            "  FROM servico sv LEFT JOIN cliente c ON c.id = sv.cliente_id "
            "  LEFT JOIN seguradora sg ON sg.id = sv.seguradora_id "
            " WHERE sv.comissao_cocorretagem = 1 AND COALESCE(sv.comissao_parcelada, 0) = 0 "
            "   AND sv.comissao_valor_plenus_recebido IS NOT NULL AND sv.data_deposito_cc IS NOT NULL"
        ).fetchall():
            item = f"{r['cliente_nome'] or 'sem cliente'} — serviço {r['numero_apolice'] or '—'}"
            _junta_coco(r["data"], r["seguradora_nome"], r["valor"], item)

        for (data, seguradora_nome), g in coco_grupos.items():
            n = len(g["itens"])
            if n == 1:
                desc = f"Cocorretagem — {seguradora_nome} — {g['itens'][0]}"
            else:
                desc = f"Cocorretagem — {seguradora_nome} ({n} repasses): " + "; ".join(g["itens"])
            linhas.append({"data": data, "tipo": "entrada", "origem": "cocorretagem",
                           "descricao": desc, "valor": round(g["valor"], 2)})

        for r in con.execute(
            "SELECT COALESCE(nf.data_depositado, nf.data_pagamento) AS data, nf.valor, nf.numero "
            "  FROM nota_fiscal nf WHERE nf.data_pagamento IS NOT NULL"
        ).fetchall():
            desc = f"Seguralta (SGA) — NF {r['numero'] or '—'}"
            linhas.append({"data": r["data"], "tipo": "entrada", "origem": "nota_fiscal",
                           "descricao": desc, "valor": float(r["valor"] or 0)})

    linhas.sort(key=lambda l: (l["data"] or "", l["tipo"]))
    return linhas


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
    valor_recebido, recibo_id, recibo_numero, origem."""
    cols_apolice = (
        "       c.nome AS cliente_nome, t.nome AS tipo_seguro_nome, "
        "       sg.nome AS seguradora_nome, "
        "       a.numero_apolice, a.premio_liquido, a.comissao_percentual, "
        "       COALESCE(a.comissao_cocorretagem, 0) AS comissao_cocorretagem ")
    # linhas de endosso: mesmas colunas, mas a cocorretagem é a do próprio endosso
    cols_endosso = cols_apolice.replace("COALESCE(a.comissao_cocorretagem, 0)",
                                        "COALESCE(e.comissao_cocorretagem, 0)")
    joins = (" FROM apolice a "
             " LEFT JOIN cliente c     ON c.id = a.cliente_id "
             " LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
             " LEFT JOIN seguradora sg ON sg.id = a.seguradora_id ")
    with conexao() as con:
        parceladas = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       r.parcela, r.data, r.valor_previsto, r.valor_recebido, "
            "       r.recibo_id, rec.numero AS recibo_numero "
            "  FROM apolice_repasse r "
            "  JOIN apolice a          ON a.id = r.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            "  LEFT JOIN recibo rec    ON rec.id = r.recibo_id "
            " ORDER BY a.id, r.ordem, r.id"
        ).fetchall()
        unicas = con.execute(
            "SELECT a.id AS apolice_id, " + cols_apolice + ", "
            "       a.comissao_valor_plenus_receber  AS valor_previsto, "
            "       a.comissao_valor_plenus_recebido AS valor_recebido, "
            "       a.data_plenus_recebido           AS data, "
            "       a.recibo_id, rec.numero AS recibo_numero "
            + joins +
            "  LEFT JOIN recibo rec ON rec.id = a.recibo_id "
            " WHERE NOT EXISTS (SELECT 1 FROM apolice_repasse r WHERE r.apolice_id = a.id) "
            " ORDER BY a.id"
        ).fetchall()
        # endossos SEM comissão parcelada: repasse "único" dos campos achatados
        endossos = con.execute(
            "SELECT a.id AS apolice_id, " + cols_endosso + ", "
            "       e.numero AS _end_num, "
            "       e.comissao_valor_plenus_receber  AS valor_previsto, "
            "       e.comissao_valor_plenus_recebido AS valor_recebido, "
            "       e.data_plenus_recebido           AS data, "
            "       e.recibo_id, rec.numero AS recibo_numero "
            "  FROM apolice_endosso e "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            "  LEFT JOIN recibo rec    ON rec.id = e.recibo_id "
            " WHERE COALESCE(e.comissao_parcelada, 0) = 0 "
            " ORDER BY a.id, e.id"
        ).fetchall()
        # endossos COM comissão parcelada: uma linha por parcela de repasse
        endossos_parc = con.execute(
            "SELECT a.id AS apolice_id, " + cols_endosso + ", "
            "       e.numero AS _end_num, r.parcela AS _end_parc, "
            "       r.data, r.valor_previsto, r.valor_recebido, "
            "       r.recibo_id, rec.numero AS recibo_numero "
            "  FROM apolice_endosso_repasse r "
            "  JOIN apolice_endosso e  ON e.id = r.endosso_id "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            "  LEFT JOIN recibo rec    ON rec.id = r.recibo_id "
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
        cols_serv = (
            "       c.nome AS cliente_nome, ts.nome AS tipo_seguro_nome, "
            "       sg.nome AS seguradora_nome, "
            "       (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, sv.premio_liquido, sv.comissao_percentual, "
            "       COALESCE(sv.comissao_cocorretagem, 0) AS comissao_cocorretagem ")
        serv_joins = (" LEFT JOIN cliente c       ON c.id = sv.cliente_id "
                      " LEFT JOIN tipo_servico ts ON ts.id = sv.tipo_servico_id "
                      " LEFT JOIN seguradora sg   ON sg.id = sv.seguradora_id ")
        # serviços: repasse parcelado (linhas de servico_repasse) ou único (campos achatados)
        servicos_parc = con.execute(
            "SELECT sv.id AS _serv_id, " + cols_serv + ", "
            "       r.parcela, r.data, r.valor_previsto, r.valor_recebido, "
            "       r.recibo_id, rec.numero AS recibo_numero "
            "  FROM servico_repasse r JOIN servico sv ON sv.id = r.servico_id "
            + serv_joins +
            "  LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            " ORDER BY sv.id, r.ordem, r.id"
        ).fetchall()
        servicos = con.execute(
            "SELECT sv.id AS _serv_id, " + cols_serv + ", "
            "       sv.comissao_valor_plenus_receber  AS valor_previsto, "
            "       sv.comissao_valor_plenus_recebido AS valor_recebido, "
            "       sv.data_plenus_recebido           AS data, "
            "       sv.recibo_id, rec.numero AS recibo_numero "
            "  FROM servico sv " + serv_joins +
            "  LEFT JOIN recibo rec ON rec.id = sv.recibo_id "
            " WHERE NOT EXISTS (SELECT 1 FROM servico_repasse r WHERE r.servico_id = sv.id) "
            " ORDER BY sv.id"
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

    for row in servicos_parc:
        d = dict(row)
        sid = d.pop("_serv_id")
        d.update(apolice_id=f"serv:{sid}", servico_id=sid, is_servico=True, origem="servico")
        linhas.append(d)
    for row in servicos:
        d = dict(row)
        if d.get("valor_previsto") is None and d.get("valor_recebido") is None:
            continue  # serviço sem repasse — fora do relatório
        sid = d.pop("_serv_id")
        d.update(apolice_id=f"serv:{sid}", servico_id=sid, is_servico=True, origem="servico",
                 parcela="única")
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
            "       e.valor AS premio_liquido, e.comissao_percentual, "
            "       COALESCE(e.comissao_cocorretagem, 0) AS cocorretagem, "
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
        # serviços — mesma regra da apólice (prêmio líquido × %)
        servicos = [dict(r) for r in con.execute(
            "SELECT sv.id AS servico_id, (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, sv.vigencia_inicio, "
            "       c.nome AS cliente_nome, ts.nome AS tipo_seguro_nome, "
            "       COALESCE(s.nome, '(sem seguradora)') AS seguradora_nome, "
            "       sv.premio_liquido, sv.comissao_percentual, "
            "       COALESCE(sv.comissao_cocorretagem, 0) AS cocorretagem, "
            "       CASE WHEN EXISTS (SELECT 1 FROM servico_comissao x WHERE x.servico_id = sv.id) "
            "            THEN (SELECT SUM(x.valor_recebido) FROM servico_comissao x WHERE x.servico_id = sv.id) "
            "            ELSE sv.comissao_valor_seguralta_recebido END AS receb_seguralta, "
            "       CASE WHEN EXISTS (SELECT 1 FROM servico_repasse x WHERE x.servico_id = sv.id) "
            "            THEN (SELECT SUM(x.valor_recebido) FROM servico_repasse x WHERE x.servico_id = sv.id) "
            "            ELSE sv.comissao_valor_plenus_recebido END AS receb_plenus, "
            "       (SELECT COUNT(DISTINCT x.parcela) FROM servico_comissao x "
            "          WHERE x.servico_id = sv.id AND x.valor_recebido IS NOT NULL) AS n_seg_pagas, "
            "       (SELECT COUNT(DISTINCT x.parcela) FROM servico_repasse x "
            "          WHERE x.servico_id = sv.id AND x.valor_recebido IS NOT NULL) AS n_ple_pagas, "
            "       CASE WHEN EXISTS (SELECT 1 FROM servico_repasse x WHERE x.servico_id = sv.id) "
            "            THEN (SELECT COALESCE(SUM(x.valor_previsto), 0) FROM servico_repasse x "
            "                    WHERE x.servico_id = sv.id AND x.valor_recebido IS NULL) "
            "            WHEN sv.comissao_valor_plenus_recebido IS NULL "
            "            THEN COALESCE(sv.comissao_valor_plenus_receber, 0) "
            "            ELSE 0 END AS ple_a_receber, "
            "       sv.recebido_relatorio_seguralta AS rel_receb_seguralta, "
            "       sv.recebido_relatorio_plenus    AS rel_receb_plenus, "
            "       1 AS is_servico "
            "  FROM servico sv "
            "  LEFT JOIN cliente c        ON c.id = sv.cliente_id "
            "  LEFT JOIN seguradora s     ON s.id = sv.seguradora_id "
            "  LEFT JOIN tipo_servico ts  ON ts.id = sv.tipo_servico_id "
            " WHERE COALESCE(sv.comissao_parcelada, 0) = 1 "
            "    OR sv.comissao_percentual IS NOT NULL "
            "    OR sv.comissao_valor_seguralta_receber IS NOT NULL "
            "    OR sv.comissao_valor_seguralta_recebido IS NOT NULL "
            "    OR sv.comissao_valor_plenus_receber IS NOT NULL "
            "    OR sv.comissao_valor_plenus_recebido IS NOT NULL"
        ).fetchall()]
    rows += endossos
    rows += consorcios
    rows += servicos
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
        rows_serv = con.execute(
            "SELECT CONCAT('serv:', sv.id) AS apolice_id, "
            "       sv.previsto_relatorio_plenus  AS prev_relatorio, "
            "       sv.recebido_relatorio_plenus  AS receb_relatorio, "
            "       COALESCE((SELECT SUM(r.valor_previsto) FROM servico_repasse r "
            "                   WHERE r.servico_id = sv.id), 0) AS prev_sistema, "
            "       COALESCE((SELECT SUM(r.valor_recebido) FROM servico_repasse r "
            "                   WHERE r.servico_id = sv.id), 0) AS receb_sistema "
            "  FROM servico sv "
            " WHERE sv.previsto_relatorio_plenus IS NOT NULL "
            "    OR sv.recebido_relatorio_plenus IS NOT NULL"
        ).fetchall()
    return {r["apolice_id"]: dict(r) for r in list(rows) + list(rows_serv)}


def comissoes_repasses_por_apolice(data_ini=None, data_fim=None, lado="plenus"):
    """Uma entrada por APÓLICE com dado de comissão, trazendo as DUAS tabelas
    (lado Seguralta = `apolice_comissao`; lado Plenus = `apolice_repasse`) para a
    grade editável do menu Entradas. Junta os mesmos dois casos do relatório:

    * parcelada (`comissao_parcelada = 1`): as linhas reais das duas tabelas;
    * único / cocorretagem: uma linha "única" sintetizada dos campos achatados
      da própria apólice (lado Seguralta sem data — não existe coluna pra isso).

    `data_ini`/`data_fim` (ISO) filtram QUAIS apólices entram (tem ao menos uma
    parcela do lado escolhido em `lado` — "plenus" (repasse, padrão) ou
    "seguralta" (comissão) — com `data` no intervalo, ou tem parcela sem data).
    NÃO recortam as linhas de dentro do bloco — o "salvar" regrava a tabela
    inteira da apólice."""
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
            "       a.data_seguralta_recebido, a.data_plenus_recebido, a.data_deposito_cc, "
            "       a.recibo_id, rec.numero AS recibo_numero "
            "  FROM apolice a "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            "  LEFT JOIN recibo rec    ON rec.id = a.recibo_id "
            " ORDER BY a.id"
        ).fetchall()
        comissoes = con.execute(
            "SELECT apolice_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM apolice_comissao ORDER BY apolice_id, ordem, id"
        ).fetchall()
        repasses = con.execute(
            "SELECT r.apolice_id, r.parcela, r.valor_previsto, r.valor_recebido, r.data, "
            "       r.recibo_id, r.data_deposito_cc, rec.numero AS recibo_numero "
            "  FROM apolice_repasse r LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            " ORDER BY r.apolice_id, r.ordem, r.id"
        ).fetchall()
        end_com = con.execute(
            "SELECT endosso_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM apolice_endosso_comissao ORDER BY endosso_id, ordem, id").fetchall()
        end_rep = con.execute(
            "SELECT r.endosso_id, r.parcela, r.valor_previsto, r.valor_recebido, r.data, "
            "       r.recibo_id, r.data_deposito_cc, rec.numero AS recibo_numero "
            "  FROM apolice_endosso_repasse r LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            " ORDER BY r.endosso_id, r.ordem, r.id").fetchall()
        endossos = con.execute(
            "SELECT e.id AS endosso_id, e.numero AS endosso_numero, e.apolice_id, "
            "       c.nome AS cliente_nome, a.tipo_seguro_id, t.nome AS tipo_seguro_nome, "
            "       sg.nome AS seguradora_nome, a.numero_apolice, "
            "       e.valor AS premio_liquido, e.comissao_percentual, "
            "       COALESCE(e.comissao_parcelada, 0) AS comissao_parcelada, "
            "       COALESCE(e.comissao_cocorretagem, 0) AS comissao_cocorretagem, "
            "       e.comissao_valor_seguralta_receber, e.comissao_valor_seguralta_recebido, "
            "       e.comissao_valor_plenus_receber, e.comissao_valor_plenus_recebido, "
            "       e.data_seguralta_recebido, e.data_plenus_recebido, e.data_deposito_cc, "
            "       e.recibo_id, rec.numero AS recibo_numero "
            "  FROM apolice_endosso e "
            "  JOIN apolice a          ON a.id = e.apolice_id "
            "  LEFT JOIN cliente c     ON c.id = a.cliente_id "
            "  LEFT JOIN tipo_seguro t ON t.id = a.tipo_seguro_id "
            "  LEFT JOIN seguradora sg ON sg.id = a.seguradora_id "
            "  LEFT JOIN recibo rec    ON rec.id = e.recibo_id "
            " ORDER BY e.id"
        ).fetchall()
        cons_com = con.execute(
            "SELECT consorcio_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM consorcio_comissao ORDER BY consorcio_id, ordem, id").fetchall()
        cons_rep = con.execute(
            "SELECT consorcio_id, parcela, valor_previsto, valor_recebido, data, "
            "       COALESCE(conferido_banco, 0) AS conferido_banco, data_deposito_cc "
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
            "       co.data_seguralta_recebido, co.data_plenus_recebido, co.data_deposito_cc, "
            "       COALESCE(co.plenus_conferido_banco, 0) AS plenus_conferido_banco "
            "  FROM consorcio co "
            "  LEFT JOIN cliente c        ON c.id = co.cliente_id "
            "  LEFT JOIN tipo_consorcio tc ON tc.id = co.tipo_consorcio_id "
            "  LEFT JOIN seguradora sg    ON sg.id = co.seguradora_id "
            " ORDER BY co.id"
        ).fetchall()
        serv_com = con.execute(
            "SELECT servico_id, parcela, valor_previsto, valor_recebido, data "
            "  FROM servico_comissao ORDER BY servico_id, ordem, id").fetchall()
        serv_rep = con.execute(
            "SELECT r.servico_id, r.parcela, r.valor_previsto, r.valor_recebido, r.data, "
            "       r.recibo_id, r.data_deposito_cc, rec.numero AS recibo_numero "
            "  FROM servico_repasse r LEFT JOIN recibo rec ON rec.id = r.recibo_id "
            " ORDER BY r.servico_id, r.ordem, r.id").fetchall()
        servicos = con.execute(
            "SELECT sv.id AS servico_id, (SELECT ap.numero_apolice FROM apolice ap WHERE ap.id = sv.apolice_id) AS numero_apolice, "
            "       c.nome AS cliente_nome, NULL AS tipo_seguro_id, ts.nome AS tipo_seguro_nome, "
            "       sg.nome AS seguradora_nome, "
            "       sv.premio_liquido, sv.comissao_percentual, "
            "       COALESCE(sv.comissao_parcelada, 0) AS comissao_parcelada, "
            "       COALESCE(sv.comissao_cocorretagem, 0) AS comissao_cocorretagem, "
            "       sv.comissao_valor_seguralta_receber, sv.comissao_valor_seguralta_recebido, "
            "       sv.comissao_valor_plenus_receber, sv.comissao_valor_plenus_recebido, "
            "       sv.data_seguralta_recebido, sv.data_plenus_recebido, sv.data_deposito_cc, "
            "       sv.recibo_id, rec.numero AS recibo_numero "
            "  FROM servico sv "
            "  LEFT JOIN cliente c        ON c.id = sv.cliente_id "
            "  LEFT JOIN tipo_servico ts  ON ts.id = sv.tipo_servico_id "
            "  LEFT JOIN seguradora sg    ON sg.id = sv.seguradora_id "
            "  LEFT JOIN recibo rec       ON rec.id = sv.recibo_id "
            " ORDER BY sv.id"
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
        """True se alguma linha tem data preenchida dentro do intervalo.
        Parcela sem data (ainda não paga) não conta — ela só entra quando
        for lançada uma data de pagamento dentro do período buscado."""
        if not data_ini and not data_fim:
            return True
        for l in linhas:
            d = l.get("data")
            if d and (not data_ini or d >= data_ini) and (not data_fim or d <= data_fim):
                return True
        return False

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
                    "recibo_id": ap["recibo_id"], "recibo_numero": ap.get("recibo_numero"),
                    "data_deposito_cc": ap.get("data_deposito_cc")}]
        if not _no_periodo(com if lado == "seguralta" else rep):
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
                    "recibo_id": e["recibo_id"], "recibo_numero": e.get("recibo_numero"),
                    "data_deposito_cc": e.get("data_deposito_cc")}]
        if not _no_periodo(com if lado == "seguralta" else rep):
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
                    "conferido_banco": co["plenus_conferido_banco"],
                    "data_deposito_cc": co.get("data_deposito_cc")}]
        if not _no_periodo(com if lado == "seguralta" else rep):
            continue
        co["is_consorcio"] = True
        co["apolice_id"] = f"cons:{cid}"
        co["consorcio_grupo"] = co.get("numero_grupo")
        co["numero_apolice"] = ("Grupo " + (co.get("numero_grupo") or "—")
                                + (" / cota " + co["numero_cota"] if co.get("numero_cota") else ""))
        co["comissoes"] = com
        co["repasses"] = rep
        saida.append(co)

    por_serv_com, por_serv_rep = {}, {}
    for r in serv_com:
        por_serv_com.setdefault(r["servico_id"], []).append(dict(r))
    for r in serv_rep:
        por_serv_rep.setdefault(r["servico_id"], []).append(dict(r))
    for row in servicos:
        sv = dict(row)
        sid = sv["servico_id"]
        if sv["comissao_parcelada"]:
            com = por_serv_com.get(sid, [])
            rep = por_serv_rep.get(sid, [])
            if not com and not rep:
                continue
        else:
            valores = (sv["comissao_valor_seguralta_receber"], sv["comissao_valor_seguralta_recebido"],
                       sv["comissao_valor_plenus_receber"], sv["comissao_valor_plenus_recebido"])
            if all(v is None for v in valores):
                continue
            com = [{"parcela": "única",
                    "valor_previsto": sv["comissao_valor_seguralta_receber"],
                    "valor_recebido": sv["comissao_valor_seguralta_recebido"],
                    "data": sv["data_seguralta_recebido"]}]
            rep = [{"parcela": "única",
                    "valor_previsto": sv["comissao_valor_plenus_receber"],
                    "valor_recebido": sv["comissao_valor_plenus_recebido"],
                    "data": sv["data_plenus_recebido"],
                    "recibo_id": sv["recibo_id"], "recibo_numero": sv.get("recibo_numero"),
                    "data_deposito_cc": sv.get("data_deposito_cc")}]
        if not _no_periodo(com if lado == "seguralta" else rep):
            continue
        sv["is_servico"] = True
        sv["apolice_id"] = f"serv:{sid}"
        sv["comissoes"] = com
        sv["repasses"] = rep
        saida.append(sv)
    return saida
