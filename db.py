"""Banco de dados do Plenus SEGURALTA - MySQL 8 (via PyMySQL).

O esquema cresce aos poucos, entao `inicializar_db()` roda `CREATE TABLE IF NOT EXISTS` +
`_migrar_esquema()` que so ACRESCENTA colunas/tabelas que faltam - nunca apaga nem recria
nada com dado dentro. Antes de qualquer criacao/migracao e depois de toda gravacao,
`fazer_backup()` grava um `mysqldump` do banco numa pasta datada (com intervalo minimo pra
nao pesar), pra que um erro de codigo ou migracao nunca custe dado real.

Conexao: bloco `db` do plenus_config.json (host / port / user / password / database /
charset). O acesso todo passa por aqui e por `repo.py`.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from datetime import datetime

import pymysql
import pymysql.cursors

_RAIZ = os.path.dirname(os.path.abspath(__file__))
# SQLite legado: so a carga unica (migrar_para_mysql.py) le este arquivo, em modo leitura.
CAMINHO_DB = os.path.join(_RAIZ, "plenus.db")
PASTA_BACKUPS = os.path.join(_RAIZ, "backups")
MAX_BACKUPS = 300
BACKUP_INTERVALO_MIN_S = 600   # nao dispara um novo mysqldump se o ultimo foi ha menos disso

_CONFIG_PATH = os.path.join(_RAIZ, "plenus_config.json")
_DB_PADRAO = {"host": "127.0.0.1", "port": 3306, "user": "plenus",
              "password": "", "database": "plenus", "charset": "utf8mb4"}

# candidatos de mysqldump.exe quando ele nao esta no PATH (instalador padrao do MySQL no Windows)
_MYSQLDUMP_CANDIDATOS = [
    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
    r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe",
    r"C:\Program Files\MySQL\MySQL Server 9.0\bin\mysqldump.exe",
]


def config_db():
    """Le o bloco `db` do plenus_config.json sobre os padroes. Usado tambem por
    backup_db.py e migrar_para_mysql.py."""
    cfg = dict(_DB_PADRAO)
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                bloco = (json.load(f) or {}).get("db") or {}
            for k, v in bloco.items():
                if not str(k).startswith("_"):
                    cfg[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    cfg["port"] = int(cfg.get("port") or 3306)
    return cfg


_ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS usuario (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome TEXT NOT NULL,
    login VARCHAR(191) NOT NULL,
    senha_hash TEXT NOT NULL,
    ativo INT NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_acesso DATETIME,
    UNIQUE KEY ix_usuario_login_unico (login)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cliente (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome TEXT NOT NULL,            -- pessoa fisica: nome; pessoa juridica: razao social
    tipo_pessoa VARCHAR(1) NOT NULL DEFAULT 'F',  -- 'F' = fisica (CPF) | 'J' = juridica (CNPJ)
    data_nascimento TEXT,          -- ISO AAAA-MM-DD (do <input type=date>)
    sexo TEXT,                     -- 'F' | 'M' | 'Outro'
    cpf VARCHAR(14),               -- so digitos, sem mascara: 11 (CPF) ou 14 (CNPJ)
    end_rua TEXT,
    end_numero TEXT,
    end_complemento TEXT,
    end_bairro TEXT,
    end_cep TEXT,                  -- so os 8 digitos
    end_cidade TEXT,
    end_estado TEXT,              -- sigla da UF ('RJ', 'SP'...)
    tel_ddd TEXT,
    tel_numero TEXT,              -- so digitos, sem o DDD
    email TEXT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- nao deixa cadastrar o mesmo CPF/CNPJ duas vezes (varios NULL sao permitidos no UNIQUE
    -- do MySQL; clientes sem documento continuam livres). Documento gravado so com digitos.
    UNIQUE KEY ix_cliente_cpf_unico (cpf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tipo_seguro (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(191) NOT NULL,
    UNIQUE KEY ix_tipo_seguro_nome_unico (nome)   -- collation padrao ja e case-insensitive
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS forma_pagamento (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(191) NOT NULL,
    UNIQUE KEY ix_forma_pagamento_nome_unico (nome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS seguradora (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(191) NOT NULL,
    UNIQUE KEY ix_seguradora_nome_unico (nome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS categoria_saida (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tipo_consorcio (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(191) NOT NULL,
    UNIQUE KEY ix_tipo_consorcio_nome_unico (nome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- campos configuraveis da cotacao (montam o formulario de cotacao)
CREATE TABLE IF NOT EXISTS cotacao_campo (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL,            -- texto | valor | numerico | data | percentual | sim_nao | selecao
    ordem INT NOT NULL DEFAULT 0,  -- ordem no formulario "Gerar cotacao"
    papel VARCHAR(40) NOT NULL DEFAULT '',    -- '' | base_parcelamento | num_parcelas
    opcoes TEXT,                              -- tipo 'selecao': uma opcao por linha ('' quando vazio)
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS apolice (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT,
    seguradora_id INT,
    tipo_seguro_id INT,
    numero_apolice TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    premio_liquido REAL,
    iof REAL,
    premio_total REAL,
    forma_pagamento_id INT,
    comissao_percentual REAL,
    comissao_valor_seguralta_receber REAL,   -- calculado: premio liquido * % / 100
    comissao_valor_plenus_receber REAL,      -- calculado: 75% do que a SEGURALTA recebeu
    comissao_valor_seguralta_recebido REAL,  -- lancado a mao
    comissao_valor_plenus_recebido REAL,     -- lancado a mao
    data_seguralta_recebido TEXT,            -- data em que a SEGURALTA recebeu (ISO), repasse unico
    data_plenus_recebido TEXT,               -- data em que a Plenus recebeu (ISO)
    plenus_conferido_banco INT NOT NULL DEFAULT 0,  -- 1 = repasse unico conferido no extrato
    comissao_parcelada INT NOT NULL DEFAULT 0,      -- 1 = repasse mensal (apolice_comissao/repasse)
    comissao_cocorretagem INT NOT NULL DEFAULT 0,   -- 1 = cocorretagem (SEGURALTA 25% / Plenus 75%)
    previsto_relatorio_seguralta REAL,
    recebido_relatorio_seguralta REAL,
    previsto_relatorio_plenus REAL,
    recebido_relatorio_plenus REAL,
    lancado_quiver INT NOT NULL DEFAULT 0,
    link_onedrive TEXT,
    veiculo_placa TEXT,                          -- so p/ seguro de automovel
    veiculo_descricao TEXT,                      -- marca / modelo / ano
    aviso_vigencia_ok INT NOT NULL DEFAULT 0,    -- 1 = cliente ja avisado da renovacao
    aviso_vigencia_ok_em TEXT,
    apolice_enviada INT NOT NULL DEFAULT 0,
    apolice_enviada_data TEXT,
    cartao_enviado INT NOT NULL DEFAULT 0,
    cartao_enviado_data TEXT,
    observacao TEXT,                             -- texto livre (anotacoes da apolice)
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_apolice_cliente (cliente_id),
    CONSTRAINT fk_apolice_cliente     FOREIGN KEY (cliente_id)        REFERENCES cliente(id),
    CONSTRAINT fk_apolice_seguradora  FOREIGN KEY (seguradora_id)     REFERENCES seguradora(id),
    CONSTRAINT fk_apolice_tiposeguro  FOREIGN KEY (tipo_seguro_id)    REFERENCES tipo_seguro(id),
    CONSTRAINT fk_apolice_formapgto   FOREIGN KEY (forma_pagamento_id) REFERENCES forma_pagamento(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS apolice_parcela (
    id INT AUTO_INCREMENT PRIMARY KEY,
    apolice_id INT NOT NULL,
    identificacao TEXT,
    data TEXT,
    valor REAL,
    paga INT NOT NULL DEFAULT 0,       -- 0 = a pagar, 1 = paga
    pago_em TEXT,                       -- data ISO em que foi marcada como paga
    aviso_ok INT NOT NULL DEFAULT 0,   -- 1 = cliente ja foi avisado desse boleto
    aviso_ok_em TEXT,
    enviado INT NOT NULL DEFAULT 0,    -- 1 = boleto ja repassado ao cliente (card "a enviar")
    enviado_em TEXT,
    KEY ix_apolice_parcela_apolice (apolice_id),
    CONSTRAINT fk_apolice_parcela_apolice FOREIGN KEY (apolice_id)
        REFERENCES apolice(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- comissao parcelada: o que a corretora recebe da seguradora, mes a mes
CREATE TABLE IF NOT EXISTS apolice_comissao (
    id INT AUTO_INCREMENT PRIMARY KEY,
    apolice_id INT NOT NULL,
    parcela TEXT,                 -- rotulo livre ("1", "4"...), pode repetir
    valor_previsto REAL,
    valor_recebido REAL,
    data TEXT,                    -- ISO
    ordem INT NOT NULL DEFAULT 0,
    KEY ix_apolice_comissao_apolice (apolice_id),
    CONSTRAINT fk_apolice_comissao_apolice FOREIGN KEY (apolice_id)
        REFERENCES apolice(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- comissao parcelada: o que a Plenus recebe da corretora (repasse), mes a mes
CREATE TABLE IF NOT EXISTS apolice_repasse (
    id INT AUTO_INCREMENT PRIMARY KEY,
    apolice_id INT NOT NULL,
    parcela TEXT,
    valor_previsto REAL,
    valor_recebido REAL,
    data TEXT,
    conferido_banco INT NOT NULL DEFAULT 0,  -- 1 = deposito conferido no extrato da Plenus
    ordem INT NOT NULL DEFAULT 0,
    KEY ix_apolice_repasse_apolice (apolice_id),
    CONSTRAINT fk_apolice_repasse_apolice FOREIGN KEY (apolice_id)
        REFERENCES apolice(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- endosso da apolice: alteracao apos a emissao
CREATE TABLE IF NOT EXISTS apolice_endosso (
    id INT AUTO_INCREMENT PRIMARY KEY,
    apolice_id INT NOT NULL,
    numero TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    motivacao TEXT,
    situacao VARCHAR(20) NOT NULL DEFAULT 'sem_alteracao',   -- 'onus' | 'devolucao' | 'sem_alteracao'
    valor REAL,                                              -- valor total do endosso
    forma_pagamento_id INT,
    veiculo_placa TEXT,                                      -- endosso de troca de veiculo
    veiculo_descricao TEXT,
    comissao_parcelada INT NOT NULL DEFAULT 0,               -- 1 = comissao mes a mes
    comissao_percentual REAL,
    comissao_valor_seguralta_receber REAL,
    comissao_valor_seguralta_recebido REAL,
    comissao_valor_plenus_receber REAL,
    comissao_valor_plenus_recebido REAL,
    data_seguralta_recebido TEXT,
    data_plenus_recebido TEXT,
    plenus_conferido_banco INT NOT NULL DEFAULT 0,
    previsto_relatorio_seguralta REAL,
    recebido_relatorio_seguralta REAL,
    previsto_relatorio_plenus REAL,
    recebido_relatorio_plenus REAL,
    lancado_quiver INT NOT NULL DEFAULT 0,
    link_onedrive TEXT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_apolice_endosso_apolice (apolice_id),
    CONSTRAINT fk_apolice_endosso_apolice FOREIGN KEY (apolice_id)
        REFERENCES apolice(id) ON DELETE CASCADE,
    CONSTRAINT fk_apolice_endosso_formapgto FOREIGN KEY (forma_pagamento_id)
        REFERENCES forma_pagamento(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS apolice_endosso_comissao (
    id INT AUTO_INCREMENT PRIMARY KEY,
    endosso_id INT NOT NULL,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    ordem INT NOT NULL DEFAULT 0,
    KEY ix_end_comissao_endosso (endosso_id),
    CONSTRAINT fk_end_comissao_endosso FOREIGN KEY (endosso_id)
        REFERENCES apolice_endosso(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS apolice_endosso_repasse (
    id INT AUTO_INCREMENT PRIMARY KEY,
    endosso_id INT NOT NULL,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    conferido_banco INT NOT NULL DEFAULT 0, ordem INT NOT NULL DEFAULT 0,
    KEY ix_end_repasse_endosso (endosso_id),
    CONSTRAINT fk_end_repasse_endosso FOREIGN KEY (endosso_id)
        REFERENCES apolice_endosso(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS apolice_endosso_parcela (
    id INT AUTO_INCREMENT PRIMARY KEY,
    endosso_id INT NOT NULL,
    identificacao TEXT,
    data TEXT,
    valor REAL,
    paga INT NOT NULL DEFAULT 0,
    pago_em TEXT,
    aviso_ok INT NOT NULL DEFAULT 0,
    aviso_ok_em TEXT,
    enviado INT NOT NULL DEFAULT 0,
    enviado_em TEXT,
    KEY ix_end_parcela_endosso (endosso_id),
    CONSTRAINT fk_end_parcela_endosso FOREIGN KEY (endosso_id)
        REFERENCES apolice_endosso(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- registro de aviso de vencimento ja enviado (pra nao repetir o mesmo marco)
CREATE TABLE IF NOT EXISTS notificacao_vencimento (
    id INT AUTO_INCREMENT PRIMARY KEY,
    apolice_id INT NOT NULL,
    marco INT NOT NULL,               -- dias que faltavam no marco (10, 5, 1...)
    vigencia_fim VARCHAR(32),         -- pra reenviar se a vigencia mudar
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ix_notif_venc_unico (apolice_id, marco, vigencia_fim),
    CONSTRAINT fk_notif_venc_apolice FOREIGN KEY (apolice_id)
        REFERENCES apolice(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- aviso de parcela de boleto a vencer (mesma ideia, por parcela)
CREATE TABLE IF NOT EXISTS notificacao_parcela (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parcela_id INT NOT NULL,
    marco INT NOT NULL,
    data_vencimento VARCHAR(32),
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ix_notif_parcela_unico (parcela_id, marco, data_vencimento),
    CONSTRAINT fk_notif_parcela_parcela FOREIGN KEY (parcela_id)
        REFERENCES apolice_parcela(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- mesmo controle de aviso, para as parcelas de boleto do ENDOSSO
CREATE TABLE IF NOT EXISTS notificacao_endosso_parcela (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parcela_id INT NOT NULL,
    marco INT NOT NULL,
    data_vencimento VARCHAR(32),
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ix_notif_end_parcela_unico (parcela_id, marco, data_vencimento),
    CONSTRAINT fk_notif_end_parcela_parcela FOREIGN KEY (parcela_id)
        REFERENCES apolice_endosso_parcela(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- consorcio: cota de um grupo, com carta de credito, parcelas mensais (boletos)
-- e comissao nos mesmos moldes da apolice.
CREATE TABLE IF NOT EXISTS consorcio (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT,
    seguradora_id INT,
    tipo_consorcio_id INT,
    carta REAL,                                  -- valor da carta de credito (base da comissao)
    numero_grupo TEXT,
    numero_cota TEXT,
    forma_pagamento_id INT,
    quantidade_parcelas INT,
    parcela_dia_vencimento TEXT,                 -- dia do mes em que a parcela vence
    situacao VARCHAR(20) NOT NULL DEFAULT 'ativo',  -- ativo|contemplado|quitado|cancelado|desistente
    forma_contemplacao TEXT,                     -- sorteio | lance
    data_contemplacao TEXT,                      -- ISO
    comissao_percentual REAL,
    comissao_valor_seguralta_receber REAL,
    comissao_valor_plenus_receber REAL,
    comissao_valor_seguralta_recebido REAL,
    comissao_valor_plenus_recebido REAL,
    data_seguralta_recebido TEXT,
    data_plenus_recebido TEXT,
    plenus_conferido_banco INT NOT NULL DEFAULT 0,
    comissao_parcelada INT NOT NULL DEFAULT 0,
    comissao_cocorretagem INT NOT NULL DEFAULT 0,
    previsto_relatorio_seguralta REAL,
    recebido_relatorio_seguralta REAL,
    previsto_relatorio_plenus REAL,
    recebido_relatorio_plenus REAL,
    lancado_quiver INT NOT NULL DEFAULT 0,
    link_onedrive TEXT,
    observacao TEXT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_consorcio_cliente (cliente_id),
    CONSTRAINT fk_consorcio_cliente    FOREIGN KEY (cliente_id)        REFERENCES cliente(id),
    CONSTRAINT fk_consorcio_seguradora FOREIGN KEY (seguradora_id)     REFERENCES seguradora(id),
    CONSTRAINT fk_consorcio_tipo       FOREIGN KEY (tipo_consorcio_id) REFERENCES tipo_consorcio(id),
    CONSTRAINT fk_consorcio_formapgto  FOREIGN KEY (forma_pagamento_id) REFERENCES forma_pagamento(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- historico do valor da parcela do consorcio
CREATE TABLE IF NOT EXISTS consorcio_parcela_valor (
    id INT AUTO_INCREMENT PRIMARY KEY,
    consorcio_id INT NOT NULL,
    valor REAL,
    data TEXT,                                   -- ISO: a partir de quando este valor vale
    ordem INT NOT NULL DEFAULT 0,
    KEY ix_cons_parcela_valor_cons (consorcio_id),
    CONSTRAINT fk_cons_parcela_valor_cons FOREIGN KEY (consorcio_id)
        REFERENCES consorcio(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consorcio_comissao (
    id INT AUTO_INCREMENT PRIMARY KEY,
    consorcio_id INT NOT NULL,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    ordem INT NOT NULL DEFAULT 0,
    KEY ix_cons_comissao_cons (consorcio_id),
    CONSTRAINT fk_cons_comissao_cons FOREIGN KEY (consorcio_id)
        REFERENCES consorcio(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consorcio_repasse (
    id INT AUTO_INCREMENT PRIMARY KEY,
    consorcio_id INT NOT NULL,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    conferido_banco INT NOT NULL DEFAULT 0, ordem INT NOT NULL DEFAULT 0,
    KEY ix_cons_repasse_cons (consorcio_id),
    CONSTRAINT fk_cons_repasse_cons FOREIGN KEY (consorcio_id)
        REFERENCES consorcio(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- boletos do consorcio: controle proprio (emissao / vencimento / pagamento / status)
CREATE TABLE IF NOT EXISTS consorcio_boleto (
    id INT AUTO_INCREMENT PRIMARY KEY,
    consorcio_id INT NOT NULL,
    identificacao TEXT,                          -- rotulo da parcela ("1/60", "12"...)
    valor REAL,
    data_emissao TEXT,
    data_vencimento TEXT,
    data_pagamento TEXT,                         -- NULL = ainda nao pago
    status VARCHAR(20) NOT NULL DEFAULT 'a_enviar',  -- 'a_enviar' | 'enviado' | 'pago'
    aviso_ok INT NOT NULL DEFAULT 0,            -- 1 = cliente ja avisado deste boleto
    aviso_ok_em TEXT,
    ordem INT NOT NULL DEFAULT 0,
    KEY ix_cons_boleto_cons (consorcio_id),
    CONSTRAINT fk_cons_boleto_cons FOREIGN KEY (consorcio_id)
        REFERENCES consorcio(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- mesmo controle de aviso de vencimento, para os boletos do CONSORCIO
CREATE TABLE IF NOT EXISTS notificacao_consorcio_boleto (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parcela_id INT NOT NULL,
    marco INT NOT NULL,
    data_vencimento VARCHAR(32),
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ix_notif_consorcio_boleto_unico (parcela_id, marco, data_vencimento),
    CONSTRAINT fk_notif_cons_boleto_parcela FOREIGN KEY (parcela_id)
        REFERENCES consorcio_boleto(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- fluxo de caixa: saidas (contas a pagar)
CREATE TABLE IF NOT EXISTS saida (
    id INT AUTO_INCREMENT PRIMARY KEY,
    descricao TEXT NOT NULL,
    categoria_id INT,
    forma_pagamento_id INT,
    valor REAL,
    data_vencimento TEXT,          -- ISO AAAA-MM-DD
    data_pagamento TEXT,           -- NULL = ainda nao paga
    numero_parcela TEXT,           -- livre ("3/6"), ou vazio
    fixo_mensal INT NOT NULL DEFAULT 0,
    serie_id TEXT,                 -- mesmo token nas linhas geradas juntas
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_saida_categoria FOREIGN KEY (categoria_id)      REFERENCES categoria_saida(id),
    CONSTRAINT fk_saida_formapgto FOREIGN KEY (forma_pagamento_id) REFERENCES forma_pagamento(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- eventos criados no Google Agenda (1 por apolice/parcela) para nao duplicar
CREATE TABLE IF NOT EXISTS evento_agenda (
    chave VARCHAR(191) PRIMARY KEY,  -- 'vigencia:<apolice_id>' | 'boleto:<parcela_id>'
    event_id TEXT NOT NULL,
    data_ref TEXT,                   -- data do evento na ultima sincronizacao
    resumo TEXT,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# colunas esperadas por tabela - o migrador acrescenta as que faltarem num banco antigo.
# (formato: coluna -> definicao MySQL usada no ALTER TABLE ADD COLUMN)
_COLUNAS_ESPERADAS = {
    "usuario": {
        "nome": "TEXT", "login": "VARCHAR(191)", "senha_hash": "TEXT",
        "ativo": "INT NOT NULL DEFAULT 1",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP", "ultimo_acesso": "DATETIME",
    },
    "cliente": {
        "nome": "TEXT", "tipo_pessoa": "VARCHAR(1) NOT NULL DEFAULT 'F'",
        "data_nascimento": "TEXT", "sexo": "TEXT", "cpf": "VARCHAR(14)",
        "end_rua": "TEXT", "end_numero": "TEXT", "end_complemento": "TEXT", "end_bairro": "TEXT",
        "end_cep": "TEXT", "end_cidade": "TEXT", "end_estado": "TEXT",
        "tel_ddd": "TEXT", "tel_numero": "TEXT", "email": "TEXT",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "atualizado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "tipo_seguro": {"nome": "VARCHAR(191)"},
    "forma_pagamento": {"nome": "VARCHAR(191)"},
    "seguradora": {"nome": "VARCHAR(191)"},
    "categoria_saida": {"nome": "TEXT"},
    "tipo_consorcio": {"nome": "VARCHAR(191)"},
    "cotacao_campo": {
        "nome": "TEXT", "tipo": "TEXT", "ordem": "INT NOT NULL DEFAULT 0",
        "papel": "VARCHAR(40) NOT NULL DEFAULT ''", "opcoes": "TEXT",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "apolice": {
        "cliente_id": "INT", "seguradora_id": "INT",
        "tipo_seguro_id": "INT", "numero_apolice": "TEXT",
        "vigencia_inicio": "TEXT", "vigencia_fim": "TEXT",
        "premio_liquido": "REAL", "iof": "REAL", "premio_total": "REAL",
        "forma_pagamento_id": "INT", "comissao_percentual": "REAL",
        "comissao_valor_seguralta_receber": "REAL", "comissao_valor_plenus_receber": "REAL",
        "comissao_valor_seguralta_recebido": "REAL", "comissao_valor_plenus_recebido": "REAL",
        "data_seguralta_recebido": "TEXT", "data_plenus_recebido": "TEXT",
        "plenus_conferido_banco": "INT NOT NULL DEFAULT 0",
        "comissao_parcelada": "INT NOT NULL DEFAULT 0",
        "comissao_cocorretagem": "INT NOT NULL DEFAULT 0",
        "previsto_relatorio_seguralta": "REAL", "recebido_relatorio_seguralta": "REAL",
        "previsto_relatorio_plenus": "REAL", "recebido_relatorio_plenus": "REAL",
        "lancado_quiver": "INT NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "veiculo_placa": "TEXT", "veiculo_descricao": "TEXT",
        "aviso_vigencia_ok": "INT NOT NULL DEFAULT 0", "aviso_vigencia_ok_em": "TEXT",
        "apolice_enviada": "INT NOT NULL DEFAULT 0", "apolice_enviada_data": "TEXT",
        "cartao_enviado": "INT NOT NULL DEFAULT 0", "cartao_enviado_data": "TEXT",
        "observacao": "TEXT",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "atualizado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "apolice_parcela": {
        "apolice_id": "INT", "identificacao": "TEXT", "data": "TEXT", "valor": "REAL",
        "paga": "INT NOT NULL DEFAULT 0", "pago_em": "TEXT",
        "aviso_ok": "INT NOT NULL DEFAULT 0", "aviso_ok_em": "TEXT",
        "enviado": "INT NOT NULL DEFAULT 0", "enviado_em": "TEXT",
    },
    "apolice_comissao": {
        "apolice_id": "INT", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT", "ordem": "INT NOT NULL DEFAULT 0",
    },
    "apolice_repasse": {
        "apolice_id": "INT", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT",
        "conferido_banco": "INT NOT NULL DEFAULT 0", "ordem": "INT NOT NULL DEFAULT 0",
    },
    "apolice_endosso": {
        "apolice_id": "INT", "numero": "TEXT",
        "vigencia_inicio": "TEXT", "vigencia_fim": "TEXT", "motivacao": "TEXT",
        "situacao": "VARCHAR(20) NOT NULL DEFAULT 'sem_alteracao'", "valor": "REAL",
        "forma_pagamento_id": "INT",
        "veiculo_placa": "TEXT", "veiculo_descricao": "TEXT",
        "comissao_parcelada": "INT NOT NULL DEFAULT 0",
        "comissao_percentual": "REAL",
        "comissao_valor_seguralta_receber": "REAL", "comissao_valor_seguralta_recebido": "REAL",
        "comissao_valor_plenus_receber": "REAL", "comissao_valor_plenus_recebido": "REAL",
        "data_seguralta_recebido": "TEXT", "data_plenus_recebido": "TEXT",
        "plenus_conferido_banco": "INT NOT NULL DEFAULT 0",
        "previsto_relatorio_seguralta": "REAL", "recebido_relatorio_seguralta": "REAL",
        "previsto_relatorio_plenus": "REAL", "recebido_relatorio_plenus": "REAL",
        "lancado_quiver": "INT NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "atualizado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "apolice_endosso_parcela": {
        "endosso_id": "INT", "identificacao": "TEXT", "data": "TEXT", "valor": "REAL",
        "paga": "INT NOT NULL DEFAULT 0", "pago_em": "TEXT",
        "aviso_ok": "INT NOT NULL DEFAULT 0", "aviso_ok_em": "TEXT",
        "enviado": "INT NOT NULL DEFAULT 0", "enviado_em": "TEXT",
    },
    "apolice_endosso_comissao": {
        "endosso_id": "INT", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT", "ordem": "INT NOT NULL DEFAULT 0",
    },
    "apolice_endosso_repasse": {
        "endosso_id": "INT", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT",
        "conferido_banco": "INT NOT NULL DEFAULT 0", "ordem": "INT NOT NULL DEFAULT 0",
    },
    "notificacao_endosso_parcela": {
        "parcela_id": "INT", "marco": "INT", "data_vencimento": "VARCHAR(32)",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "notificacao_parcela": {
        "parcela_id": "INT", "marco": "INT", "data_vencimento": "VARCHAR(32)",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "consorcio": {
        "cliente_id": "INT", "seguradora_id": "INT", "tipo_consorcio_id": "INT",
        "carta": "REAL", "numero_grupo": "TEXT", "numero_cota": "TEXT",
        "forma_pagamento_id": "INT", "quantidade_parcelas": "INT",
        "parcela_dia_vencimento": "TEXT",
        "situacao": "VARCHAR(20) NOT NULL DEFAULT 'ativo'",
        "forma_contemplacao": "TEXT", "data_contemplacao": "TEXT",
        "comissao_percentual": "REAL",
        "comissao_valor_seguralta_receber": "REAL", "comissao_valor_plenus_receber": "REAL",
        "comissao_valor_seguralta_recebido": "REAL", "comissao_valor_plenus_recebido": "REAL",
        "data_seguralta_recebido": "TEXT", "data_plenus_recebido": "TEXT",
        "plenus_conferido_banco": "INT NOT NULL DEFAULT 0",
        "comissao_parcelada": "INT NOT NULL DEFAULT 0",
        "comissao_cocorretagem": "INT NOT NULL DEFAULT 0",
        "previsto_relatorio_seguralta": "REAL", "recebido_relatorio_seguralta": "REAL",
        "previsto_relatorio_plenus": "REAL", "recebido_relatorio_plenus": "REAL",
        "lancado_quiver": "INT NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "observacao": "TEXT",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "atualizado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "consorcio_parcela_valor": {
        "consorcio_id": "INT", "valor": "REAL", "data": "TEXT",
        "ordem": "INT NOT NULL DEFAULT 0",
    },
    "consorcio_comissao": {
        "consorcio_id": "INT", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT", "ordem": "INT NOT NULL DEFAULT 0",
    },
    "consorcio_repasse": {
        "consorcio_id": "INT", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT",
        "conferido_banco": "INT NOT NULL DEFAULT 0", "ordem": "INT NOT NULL DEFAULT 0",
    },
    "consorcio_boleto": {
        "consorcio_id": "INT", "identificacao": "TEXT", "valor": "REAL",
        "data_emissao": "TEXT", "data_vencimento": "TEXT", "data_pagamento": "TEXT",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'a_enviar'",
        "aviso_ok": "INT NOT NULL DEFAULT 0", "aviso_ok_em": "TEXT",
        "ordem": "INT NOT NULL DEFAULT 0",
    },
    "notificacao_consorcio_boleto": {
        "parcela_id": "INT", "marco": "INT", "data_vencimento": "VARCHAR(32)",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "evento_agenda": {
        "chave": "VARCHAR(191)", "event_id": "TEXT", "data_ref": "TEXT", "resumo": "TEXT",
        "atualizado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "saida": {
        "descricao": "TEXT", "categoria_id": "INT", "forma_pagamento_id": "INT",
        "valor": "REAL",
        "data_vencimento": "TEXT", "data_pagamento": "TEXT", "numero_parcela": "TEXT",
        "fixo_mensal": "INT NOT NULL DEFAULT 0", "serie_id": "TEXT",
        "criado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "atualizado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "notificacao_vencimento": {
        "apolice_id": "INT", "marco": "INT", "vigencia_fim": "VARCHAR(32)",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
}


class _Conexao:
    """Wrapper fino sobre a conexao do PyMySQL que expoe a mesma API que o `repo.py`
    ja usava com o sqlite3: `con.execute(sql, params)` devolve um cursor (DictCursor),
    `con.executescript(...)`, `con.lastrowid`, e commit/rollback no `with`."""

    def __init__(self, raw):
        self._raw = raw
        self._ultimo_cur = None

    def execute(self, sql, params=None):
        cur = self._raw.cursor()
        # params falsy (None / tupla vazia) -> None, pra o PyMySQL NAO tentar formatar a
        # query (deixa `%` literal de `LIKE '%x%'` em paz em queries sem parametro).
        cur.execute(sql, params if params else None)
        self._ultimo_cur = cur
        return cur

    def executemany(self, sql, seq):
        cur = self._raw.cursor()
        cur.executemany(sql, list(seq))
        self._ultimo_cur = cur
        return cur

    def executescript(self, script):
        # tira os comentarios `-- ...` (inclusive os que tem ';' no meio) antes de dividir
        limpo = re.sub(r"--[^\n]*", "", script)
        for stmt in limpo.split(";"):
            if stmt.strip():
                self.execute(stmt)

    @property
    def lastrowid(self):
        return self._ultimo_cur.lastrowid if self._ultimo_cur is not None else None

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        return False


@contextlib.contextmanager
def conexao():
    cfg = config_db()
    raw = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg.get("password") or "", database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=10, read_timeout=30, write_timeout=30,
    )
    con = _Conexao(raw)
    try:
        with con:
            yield con
    finally:
        raw.close()


def _um(cur):
    """Primeiro valor da primeira linha (para SELECT COUNT(*)/SUM()/MAX() etc.)."""
    row = cur.fetchone()
    return next(iter(row.values())) if row else None


def _colunas_da_tabela(con, tabela):
    base = config_db()["database"]
    return {r["c"] for r in con.execute(
        "SELECT LOWER(column_name) AS c FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s", (base, tabela)).fetchall()}


def inicializar_db():
    fazer_backup()  # snapshot ANTES de qualquer criacao/migracao
    with conexao() as con:
        con.execute("SET FOREIGN_KEY_CHECKS = 0")
        con.executescript(_ESQUEMA_SQL)
        con.execute("SET FOREIGN_KEY_CHECKS = 1")
        _migrar_esquema(con)
        _backfill_dados(con)


def _migrar_esquema(con):
    for tabela, colunas in _COLUNAS_ESPERADAS.items():
        existentes = _colunas_da_tabela(con, tabela)
        if not existentes:
            continue  # tabela nem existe ainda (criada pelo _ESQUEMA_SQL acima) - nada a migrar
        for coluna, definicao in colunas.items():
            if coluna.lower() not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def _backfill_dados(con):
    """Preenchimentos unicos de dados apos a migracao de esquema (so coisas idempotentes)."""
    cols = _colunas_da_tabela(con, "apolice")
    # comissao_valor (coluna antiga) -> comissao_valor_seguralta_receber
    if {"comissao_valor", "comissao_valor_seguralta_receber"} <= cols:
        con.execute(
            "UPDATE apolice SET comissao_valor_seguralta_receber = comissao_valor "
            "WHERE comissao_valor_seguralta_receber IS NULL AND comissao_valor IS NOT NULL"
        )

    # apolice_repasse: valor/status/data_pagamento -> valor_previsto/valor_recebido/data
    rep = _colunas_da_tabela(con, "apolice_repasse")
    if {"valor", "status", "data_pagamento", "valor_previsto"} <= rep:
        con.execute(
            "UPDATE apolice_repasse SET "
            "  valor_previsto = valor, "
            "  valor_recebido = CASE WHEN status = 'pago' THEN valor END, "
            "  data = data_pagamento "
            "WHERE valor_previsto IS NULL AND valor IS NOT NULL"
        )

    # cotacao_campo.papel: 1a migracao herda os papeis dos nomes usados ate agora.
    cc = _colunas_da_tabela(con, "cotacao_campo")
    if "papel" in cc:
        ja_tem = _um(con.execute(
            "SELECT COUNT(*) FROM cotacao_campo WHERE papel IS NOT NULL AND papel <> ''"
        ))
        if not ja_tem:
            def _n(s):
                t = unicodedata.normalize("NFKD", (s or "").strip().lower())
                return "".join(c for c in t if not unicodedata.combining(c))
            usados = set()
            for row in con.execute(
                    "SELECT id, nome FROM cotacao_campo ORDER BY ordem, id").fetchall():
                cid, nome = row["id"], row["nome"]
                n = _n(nome)
                if n == "valor do seguro" and "base_parcelamento" not in usados:
                    con.execute("UPDATE cotacao_campo SET papel = 'base_parcelamento' WHERE id = %s", (cid,))
                    usados.add("base_parcelamento")
                elif n == "no de parcelas" and "num_parcelas" not in usados:
                    con.execute("UPDATE cotacao_campo SET papel = 'num_parcelas' WHERE id = %s", (cid,))
                    usados.add("num_parcelas")

    # tipos antigos 'nivel' / 'livre_referenciada' viram 'selecao' com as opcoes fixas.
    if "opcoes" in cc:
        for tipo_antigo, opcoes in (("nivel", "Simples\nIntermediario\nCompleto"),
                                    ("livre_referenciada", "Livre escolha\nReferenciada")):
            con.execute(
                "UPDATE cotacao_campo SET tipo = 'selecao', opcoes = %s "
                "WHERE tipo = %s AND (opcoes IS NULL OR opcoes = '')",
                (opcoes, tipo_antigo),
            )


# ---------- backup (mysqldump) ----------

_ultimo_dump_mono = 0.0  # time.monotonic() do ultimo dump feito nesta execucao


def _mysqldump_bin():
    return (shutil.which("mysqldump")
            or next((p for p in _MYSQLDUMP_CANDIDATOS if os.path.exists(p)), None))


def _ultimo_backup_ts():
    """mtime da pasta de backup mais recente que tenha um plenus.sql dentro (0 se nao ha)."""
    if not os.path.isdir(PASTA_BACKUPS):
        return 0.0
    ts = 0.0
    for n in os.listdir(PASTA_BACKUPS):
        d = os.path.join(PASTA_BACKUPS, n)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "plenus.sql")):
            ts = max(ts, os.path.getmtime(d))
    return ts


def fazer_backup(forcar=False):
    """mysqldump do banco `plenus` para backups/<carimbo>/plenus.sql, com intervalo minimo
    (BACKUP_INTERVALO_MIN_S) pra nao rodar a cada gravacao. Nunca levanta excecao."""
    global _ultimo_dump_mono
    agora = time.monotonic()
    if not forcar:
        if _ultimo_dump_mono and (agora - _ultimo_dump_mono) < BACKUP_INTERVALO_MIN_S:
            return None
        if (time.time() - _ultimo_backup_ts()) < BACKUP_INTERVALO_MIN_S:
            _ultimo_dump_mono = agora
            return None

    dump = _mysqldump_bin()
    if not dump:
        print("AVISO(backup): mysqldump nao encontrado no PATH nem em Program Files; backup pulado")
        return None

    cfg = config_db()
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = os.path.join(PASTA_BACKUPS, carimbo)
    os.makedirs(destino, exist_ok=True)
    arq = os.path.join(destino, "plenus.sql")
    # args que funcionam no mysqldump do MySQL 8 E no do MariaDB (sem --single-transaction,
    # que exige FLUSH_TABLES; sem --set-gtid-purged, que só existe no MySQL)
    cmd = [dump, "--host", str(cfg["host"]), "--port", str(cfg["port"]),
           "--user", str(cfg["user"]), "--no-tablespaces", "--skip-lock-tables",
           str(cfg["database"])]
    env = {**os.environ, "MYSQL_PWD": str(cfg.get("password") or "")}
    try:
        with open(arq, "w", encoding="utf-8", newline="\n") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env,
                           check=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"AVISO(backup): mysqldump falhou ({e!r}); backup pulado")
        shutil.rmtree(destino, ignore_errors=True)
        return None

    _ultimo_dump_mono = agora
    _rotacionar_backups()
    return destino


def _rotacionar_backups():
    if not os.path.isdir(PASTA_BACKUPS):
        return
    pastas = sorted(n for n in os.listdir(PASTA_BACKUPS) if os.path.isdir(os.path.join(PASTA_BACKUPS, n)))
    for nome in pastas[:-MAX_BACKUPS] if len(pastas) > MAX_BACKUPS else []:
        shutil.rmtree(os.path.join(PASTA_BACKUPS, nome), ignore_errors=True)
