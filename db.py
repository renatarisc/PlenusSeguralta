"""Banco de dados do Plenus SEGURALTA.

SQLite nativo (sem servidor separado - volume pequeno). O esquema cresce aos poucos, então
`inicializar_db()` roda `CREATE TABLE IF NOT EXISTS` + `_migrar_esquema()` que só ACRESCENTA
colunas/tabelas que faltam - nunca apaga nem recria nada com dado dentro. Antes de qualquer
criação/migração e depois de toda gravação, `fazer_backup()` grava um snapshot do .db numa pasta
datada, pra que um erro de código ou migração nunca custe dado real.
"""

import contextlib
import os
import shutil
import sqlite3
from datetime import datetime

_RAIZ = os.path.dirname(os.path.abspath(__file__))
CAMINHO_DB = os.path.join(_RAIZ, "plenus.db")
PASTA_BACKUPS = os.path.join(_RAIZ, "backups")
MAX_BACKUPS = 300

_ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS usuario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    senha_hash TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_acesso TEXT
);

CREATE TABLE IF NOT EXISTS cliente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    data_nascimento TEXT,          -- ISO AAAA-MM-DD (do <input type=date>)
    sexo TEXT,                     -- 'F' | 'M' | 'Outro'
    cpf TEXT,                      -- só os 11 dígitos, sem máscara
    end_rua TEXT,
    end_numero TEXT,
    end_complemento TEXT,
    end_bairro TEXT,
    end_cep TEXT,                  -- só os 8 dígitos
    end_cidade TEXT,
    end_estado TEXT,              -- sigla da UF ('RJ', 'SP'...)
    tel_ddd TEXT,
    tel_numero TEXT,              -- só dígitos, sem o DDD
    email TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tipo_seguro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forma_pagamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguradora (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apolice (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER REFERENCES cliente(id),
    seguradora_id INTEGER REFERENCES seguradora(id),
    tipo_seguro_id INTEGER REFERENCES tipo_seguro(id),
    numero_apolice TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    premio_liquido REAL,
    iof REAL,
    premio_total REAL,
    forma_pagamento_id INTEGER REFERENCES forma_pagamento(id),
    comissao_percentual REAL,
    comissao_valor REAL,
    lancado_quiver INTEGER NOT NULL DEFAULT 0,   -- 0 = não, 1 = sim
    link_onedrive TEXT,
    veiculo_placa TEXT,                          -- só p/ seguro de automóvel
    veiculo_descricao TEXT,                      -- marca / modelo / ano
    apolice_enviada INTEGER NOT NULL DEFAULT 0,
    apolice_enviada_data TEXT,
    cartao_enviado INTEGER NOT NULL DEFAULT 0,
    cartao_enviado_data TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS apolice_parcela (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apolice_id INTEGER NOT NULL REFERENCES apolice(id) ON DELETE CASCADE,
    identificacao TEXT,
    data TEXT,
    valor REAL
);

-- registro de aviso de vencimento já enviado (pra não repetir o mesmo marco)
CREATE TABLE IF NOT EXISTS notificacao_vencimento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apolice_id INTEGER NOT NULL REFERENCES apolice(id) ON DELETE CASCADE,
    marco INTEGER NOT NULL,            -- dias que faltavam no marco (10, 5, 1...)
    vigencia_fim TEXT,                 -- pra reenviar se a vigência mudar
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_notif_venc_unico
    ON notificacao_vencimento (apolice_id, marco, vigencia_fim);
"""

# colunas esperadas por tabela - o migrador acrescenta as que faltarem num banco antigo.
# (formato: coluna -> definição usada no ALTER TABLE ADD COLUMN)
_COLUNAS_ESPERADAS = {
    "usuario": {
        "nome": "TEXT", "login": "TEXT", "senha_hash": "TEXT",
        "ativo": "INTEGER NOT NULL DEFAULT 1",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))", "ultimo_acesso": "TEXT",
    },
    "cliente": {
        "nome": "TEXT", "data_nascimento": "TEXT", "sexo": "TEXT", "cpf": "TEXT",
        "end_rua": "TEXT", "end_numero": "TEXT", "end_complemento": "TEXT", "end_bairro": "TEXT",
        "end_cep": "TEXT", "end_cidade": "TEXT", "end_estado": "TEXT",
        "tel_ddd": "TEXT", "tel_numero": "TEXT", "email": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "tipo_seguro": {"nome": "TEXT"},
    "forma_pagamento": {"nome": "TEXT"},
    "seguradora": {"nome": "TEXT"},
    "apolice": {
        "cliente_id": "INTEGER", "seguradora_id": "INTEGER",
        "tipo_seguro_id": "INTEGER", "numero_apolice": "TEXT",
        "vigencia_inicio": "TEXT", "vigencia_fim": "TEXT",
        "premio_liquido": "REAL", "iof": "REAL", "premio_total": "REAL",
        "forma_pagamento_id": "INTEGER", "comissao_percentual": "REAL", "comissao_valor": "REAL",
        "lancado_quiver": "INTEGER NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "veiculo_placa": "TEXT", "veiculo_descricao": "TEXT",
        "apolice_enviada": "INTEGER NOT NULL DEFAULT 0", "apolice_enviada_data": "TEXT",
        "cartao_enviado": "INTEGER NOT NULL DEFAULT 0", "cartao_enviado_data": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "apolice_parcela": {"apolice_id": "INTEGER", "identificacao": "TEXT", "data": "TEXT", "valor": "REAL"},
    "notificacao_vencimento": {
        "apolice_id": "INTEGER", "marco": "INTEGER", "vigencia_fim": "TEXT",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
}


@contextlib.contextmanager
def conexao():
    con = sqlite3.connect(CAMINHO_DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")  # espera até 10s por um lock (2 usuários ao mesmo tempo)
    try:
        with con:
            yield con
    finally:
        con.close()


def inicializar_db():
    fazer_backup()  # snapshot ANTES de qualquer criação/migração
    with conexao() as con:
        con.executescript(_ESQUEMA_SQL)
        _migrar_esquema(con)


def _migrar_esquema(con):
    for tabela, colunas in _COLUNAS_ESPERADAS.items():
        existentes = {l["name"] for l in con.execute(f"PRAGMA table_info({tabela})")}
        if not existentes:
            continue  # tabela nem existe ainda (criada pelo _ESQUEMA_SQL acima) - nada a migrar
        for coluna, definicao in colunas.items():
            if coluna not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


# ---------- backup ----------

def fazer_backup():
    if not os.path.exists(CAMINHO_DB):
        return None
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = os.path.join(PASTA_BACKUPS, carimbo)
    os.makedirs(destino, exist_ok=True)
    shutil.copy2(CAMINHO_DB, os.path.join(destino, "plenus.db"))
    _rotacionar_backups()
    return destino


def _rotacionar_backups():
    if not os.path.isdir(PASTA_BACKUPS):
        return
    pastas = sorted(n for n in os.listdir(PASTA_BACKUPS) if os.path.isdir(os.path.join(PASTA_BACKUPS, n)))
    for nome in pastas[:-MAX_BACKUPS] if len(pastas) > MAX_BACKUPS else []:
        shutil.rmtree(os.path.join(PASTA_BACKUPS, nome), ignore_errors=True)
