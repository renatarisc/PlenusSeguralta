"""Consultas ao banco, por entidade. Cresce junto com o sistema.

Cada função abre sua própria conexão (via db.conexao) e devolve dicts / listas de dicts.
"""

from db import conexao, fazer_backup
from validacao import so_digitos

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
        if busca:
            like = f"%{busca.strip()}%"
            linhas = con.execute(
                "SELECT id, nome, cpf, end_cidade, end_estado, tel_ddd, tel_numero, email "
                "FROM cliente WHERE nome LIKE ? OR cpf LIKE ? ORDER BY nome COLLATE NOCASE",
                (like, f"%{so_digitos(busca)}%"),
            ).fetchall()
        else:
            linhas = con.execute(
                "SELECT id, nome, cpf, end_cidade, end_estado, tel_ddd, tel_numero, email "
                "FROM cliente ORDER BY nome COLLATE NOCASE"
            ).fetchall()
        return [dict(l) for l in linhas]


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

_TABELAS_SIMPLES = {"tipo_seguro", "forma_pagamento"}


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
