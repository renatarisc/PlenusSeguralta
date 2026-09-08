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
import unicodedata
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
    nome TEXT NOT NULL,            -- pessoa física: nome; pessoa jurídica: razão social
    tipo_pessoa TEXT NOT NULL DEFAULT 'F',  -- 'F' = física (CPF) | 'J' = jurídica (CNPJ)
    data_nascimento TEXT,          -- ISO AAAA-MM-DD (do <input type=date>)
    sexo TEXT,                     -- 'F' | 'M' | 'Outro'
    cpf TEXT,                      -- só dígitos, sem máscara: 11 (CPF) ou 14 (CNPJ)
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
-- não deixa cadastrar o mesmo CPF duas vezes (só vale quando o CPF foi informado;
-- clientes sem CPF continuam livres). CPF é gravado só com dígitos.
CREATE UNIQUE INDEX IF NOT EXISTS ix_cliente_cpf_unico
    ON cliente (cpf) WHERE cpf IS NOT NULL AND cpf <> '';

CREATE TABLE IF NOT EXISTS tipo_seguro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);
-- não deixa cadastrar o mesmo tipo de seguro duas vezes (ignora maiúsc./minúsc.)
CREATE UNIQUE INDEX IF NOT EXISTS ix_tipo_seguro_nome_unico
    ON tipo_seguro (nome COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS forma_pagamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);
-- não deixa cadastrar a mesma forma de pagamento duas vezes (ignora maiúsc./minúsc.)
CREATE UNIQUE INDEX IF NOT EXISTS ix_forma_pagamento_nome_unico
    ON forma_pagamento (nome COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS seguradora (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);
-- não deixa cadastrar a mesma seguradora duas vezes (ignora maiúsc./minúsc.)
CREATE UNIQUE INDEX IF NOT EXISTS ix_seguradora_nome_unico
    ON seguradora (nome COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS categoria_saida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tipo_consorcio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);
-- não deixa cadastrar o mesmo tipo de consórcio duas vezes (ignora maiúsc./minúsc.)
CREATE UNIQUE INDEX IF NOT EXISTS ix_tipo_consorcio_nome_unico
    ON tipo_consorcio (nome COLLATE NOCASE);

-- campos configuráveis da cotação (montam o formulário de cotação)
CREATE TABLE IF NOT EXISTS cotacao_campo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL,            -- texto | valor | numerico | data | percentual | sim_nao | selecao
    ordem INTEGER NOT NULL DEFAULT 0,  -- ordem no formulário "Gerar cotação"
    papel TEXT NOT NULL DEFAULT '',    -- '' | base_parcelamento | num_parcelas (usados no cálculo do PDF)
    opcoes TEXT NOT NULL DEFAULT '',   -- tipo 'selecao': uma opção por linha
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
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
    comissao_valor_seguralta_receber REAL,   -- calculado: prêmio líquido * % / 100
    comissao_valor_plenus_receber REAL,      -- calculado: 75% do que a SEGURALTA recebeu
    comissao_valor_seguralta_recebido REAL,  -- lançado à mão
    comissao_valor_plenus_recebido REAL,     -- lançado à mão
    data_seguralta_recebido TEXT,            -- data em que a SEGURALTA recebeu (ISO), repasse único
    data_plenus_recebido TEXT,               -- data em que a Plenus recebeu (ISO)
    plenus_conferido_banco INTEGER NOT NULL DEFAULT 0,  -- 1 = repasse único conferido no extrato bancário da Plenus
    comissao_parcelada INTEGER NOT NULL DEFAULT 0,  -- 1 = repasse mensal (usa apolice_comissao/apolice_repasse)
    comissao_cocorretagem INTEGER NOT NULL DEFAULT 0,  -- 1 = cocorretagem (SEGURALTA 25% / Plenus 75% da comissão, sem repasse)
    -- totais que o RELATÓRIO da corretora informa (p/ conferir divergência vs. soma do sistema)
    previsto_relatorio_seguralta REAL,
    recebido_relatorio_seguralta REAL,
    previsto_relatorio_plenus REAL,
    recebido_relatorio_plenus REAL,
    lancado_quiver INTEGER NOT NULL DEFAULT 0,   -- 0 = não, 1 = sim
    link_onedrive TEXT,
    veiculo_placa TEXT,                          -- só p/ seguro de automóvel
    veiculo_descricao TEXT,                      -- marca / modelo / ano
    aviso_vigencia_ok INTEGER NOT NULL DEFAULT 0,  -- 1 = cliente já avisado da renovação (para o e-mail diário)
    aviso_vigencia_ok_em TEXT,
    apolice_enviada INTEGER NOT NULL DEFAULT 0,
    apolice_enviada_data TEXT,
    cartao_enviado INTEGER NOT NULL DEFAULT 0,
    cartao_enviado_data TEXT,
    observacao TEXT,                             -- texto livre (anotações da apólice)
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS apolice_parcela (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apolice_id INTEGER NOT NULL REFERENCES apolice(id) ON DELETE CASCADE,
    identificacao TEXT,
    data TEXT,
    valor REAL,
    paga INTEGER NOT NULL DEFAULT 0,   -- 0 = a pagar, 1 = paga
    pago_em TEXT,                       -- data ISO em que foi marcada como paga
    aviso_ok INTEGER NOT NULL DEFAULT 0,  -- 1 = cliente já foi avisado desse boleto (para o e-mail diário)
    aviso_ok_em TEXT
);

-- comissão parcelada: o que a corretora recebe da seguradora, mês a mês
CREATE TABLE IF NOT EXISTS apolice_comissao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apolice_id INTEGER NOT NULL REFERENCES apolice(id) ON DELETE CASCADE,
    parcela TEXT,                 -- rótulo livre ("1", "4"...), pode repetir
    valor_previsto REAL,
    valor_recebido REAL,
    data TEXT,                    -- ISO
    ordem INTEGER NOT NULL DEFAULT 0
);

-- comissão parcelada: o que a Plenus recebe da corretora (repasse), mês a mês
-- (mesma estrutura da apolice_comissao)
CREATE TABLE IF NOT EXISTS apolice_repasse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apolice_id INTEGER NOT NULL REFERENCES apolice(id) ON DELETE CASCADE,
    parcela TEXT,
    valor_previsto REAL,
    valor_recebido REAL,
    data TEXT,
    conferido_banco INTEGER NOT NULL DEFAULT 0,  -- 1 = depósito conferido no extrato bancário da Plenus
    ordem INTEGER NOT NULL DEFAULT 0
);

-- endosso da apólice: alteração após a emissão (número próprio, vigência, motivo,
-- situação financeira e comissão própria). Ônus/devolução NÃO geram parcelas de
-- pagamento — o valor fica só como registro.
CREATE TABLE IF NOT EXISTS apolice_endosso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apolice_id INTEGER NOT NULL REFERENCES apolice(id) ON DELETE CASCADE,
    numero TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    motivacao TEXT,
    situacao TEXT NOT NULL DEFAULT 'sem_alteracao',   -- 'onus' | 'devolucao' | 'sem_alteracao'
    valor REAL,                                        -- valor total do endosso (ônus/devolução)
    forma_pagamento_id INTEGER REFERENCES forma_pagamento(id),
    veiculo_placa TEXT,                                -- endosso de troca de veículo
    veiculo_descricao TEXT,
    comissao_parcelada INTEGER NOT NULL DEFAULT 0,     -- 1 = comissão mês a mês (tabelas-filhas)
    comissao_percentual REAL,
    comissao_valor_seguralta_receber REAL,
    comissao_valor_seguralta_recebido REAL,
    comissao_valor_plenus_receber REAL,
    comissao_valor_plenus_recebido REAL,
    data_seguralta_recebido TEXT,
    data_plenus_recebido TEXT,
    plenus_conferido_banco INTEGER NOT NULL DEFAULT 0,
    previsto_relatorio_seguralta REAL,
    recebido_relatorio_seguralta REAL,
    previsto_relatorio_plenus REAL,
    recebido_relatorio_plenus REAL,
    lancado_quiver INTEGER NOT NULL DEFAULT 0,
    link_onedrive TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- comissão parcelada do endosso (mesma ideia de apolice_comissao / apolice_repasse)
CREATE TABLE IF NOT EXISTS apolice_endosso_comissao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endosso_id INTEGER NOT NULL REFERENCES apolice_endosso(id) ON DELETE CASCADE,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    ordem INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS apolice_endosso_repasse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endosso_id INTEGER NOT NULL REFERENCES apolice_endosso(id) ON DELETE CASCADE,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    conferido_banco INTEGER NOT NULL DEFAULT 0, ordem INTEGER NOT NULL DEFAULT 0
);

-- parcelas de pagamento do endosso (mesma ideia de apolice_parcela)
CREATE TABLE IF NOT EXISTS apolice_endosso_parcela (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endosso_id INTEGER NOT NULL REFERENCES apolice_endosso(id) ON DELETE CASCADE,
    identificacao TEXT,
    data TEXT,
    valor REAL,
    paga INTEGER NOT NULL DEFAULT 0,
    pago_em TEXT,
    aviso_ok INTEGER NOT NULL DEFAULT 0,
    aviso_ok_em TEXT
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

-- aviso de parcela de boleto a vencer (mesma ideia, por parcela)
CREATE TABLE IF NOT EXISTS notificacao_parcela (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parcela_id INTEGER NOT NULL REFERENCES apolice_parcela(id) ON DELETE CASCADE,
    marco INTEGER NOT NULL,
    data_vencimento TEXT,
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_notif_parcela_unico
    ON notificacao_parcela (parcela_id, marco, data_vencimento);

-- mesmo controle de aviso, para as parcelas de boleto do ENDOSSO
CREATE TABLE IF NOT EXISTS notificacao_endosso_parcela (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parcela_id INTEGER NOT NULL REFERENCES apolice_endosso_parcela(id) ON DELETE CASCADE,
    marco INTEGER NOT NULL,
    data_vencimento TEXT,
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_notif_end_parcela_unico
    ON notificacao_endosso_parcela (parcela_id, marco, data_vencimento);

-- consórcio: cota de um grupo, com carta de crédito, parcelas mensais (boletos)
-- e comissão nos mesmos moldes da apólice (cocorretagem, parcelada, 25/75).
CREATE TABLE IF NOT EXISTS consorcio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER REFERENCES cliente(id),
    seguradora_id INTEGER REFERENCES seguradora(id),
    tipo_consorcio_id INTEGER REFERENCES tipo_consorcio(id),
    carta REAL,                                  -- valor da carta de crédito (base da comissão)
    numero_grupo TEXT,
    numero_cota TEXT,
    forma_pagamento_id INTEGER REFERENCES forma_pagamento(id),
    quantidade_parcelas INTEGER,
    parcela_dia_vencimento TEXT,                 -- dia do mês em que a parcela vence
    situacao TEXT NOT NULL DEFAULT 'ativo',      -- ativo | contemplado | quitado | cancelado | desistente
    forma_contemplacao TEXT,                     -- sorteio | lance
    data_contemplacao TEXT,                      -- ISO
    -- comissão (idêntica à da apólice) — calculada sobre o valor da carta
    comissao_percentual REAL,
    comissao_valor_seguralta_receber REAL,
    comissao_valor_plenus_receber REAL,
    comissao_valor_seguralta_recebido REAL,
    comissao_valor_plenus_recebido REAL,
    data_seguralta_recebido TEXT,
    data_plenus_recebido TEXT,
    plenus_conferido_banco INTEGER NOT NULL DEFAULT 0,
    comissao_parcelada INTEGER NOT NULL DEFAULT 0,
    comissao_cocorretagem INTEGER NOT NULL DEFAULT 0,
    previsto_relatorio_seguralta REAL,
    recebido_relatorio_seguralta REAL,
    previsto_relatorio_plenus REAL,
    recebido_relatorio_plenus REAL,
    lancado_quiver INTEGER NOT NULL DEFAULT 0,
    link_onedrive TEXT,
    observacao TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- histórico do valor da parcela do consórcio: o 1º registro é o valor inicial;
-- cada reajuste entra como uma nova linha (valor + data em que passou a vigorar).
CREATE TABLE IF NOT EXISTS consorcio_parcela_valor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consorcio_id INTEGER NOT NULL REFERENCES consorcio(id) ON DELETE CASCADE,
    valor REAL,
    data TEXT,                                   -- ISO: a partir de quando este valor vale
    ordem INTEGER NOT NULL DEFAULT 0
);

-- comissão parcelada do consórcio (mesma ideia de apolice_comissao / apolice_repasse)
CREATE TABLE IF NOT EXISTS consorcio_comissao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consorcio_id INTEGER NOT NULL REFERENCES consorcio(id) ON DELETE CASCADE,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    ordem INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS consorcio_repasse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consorcio_id INTEGER NOT NULL REFERENCES consorcio(id) ON DELETE CASCADE,
    parcela TEXT, valor_previsto REAL, valor_recebido REAL, data TEXT,
    conferido_banco INTEGER NOT NULL DEFAULT 0, ordem INTEGER NOT NULL DEFAULT 0
);

-- boletos do consórcio: controle próprio (emissão / vencimento / pagamento / status)
CREATE TABLE IF NOT EXISTS consorcio_boleto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consorcio_id INTEGER NOT NULL REFERENCES consorcio(id) ON DELETE CASCADE,
    identificacao TEXT,                          -- rótulo da parcela ("1/60", "12"...)
    valor REAL,
    data_emissao TEXT,
    data_vencimento TEXT,
    data_pagamento TEXT,                         -- NULL = ainda não pago
    status TEXT NOT NULL DEFAULT 'a_enviar',     -- 'a_enviar' (recém-gerado) | 'enviado' | 'pago'
    aviso_ok INTEGER NOT NULL DEFAULT 0,         -- 1 = cliente já avisado deste boleto (e-mail diário)
    aviso_ok_em TEXT,
    ordem INTEGER NOT NULL DEFAULT 0
);

-- mesmo controle de aviso de vencimento, para os boletos do CONSÓRCIO
-- (a coluna se chama parcela_id p/ reaproveitar as mesmas funções dos outros boletos)
CREATE TABLE IF NOT EXISTS notificacao_consorcio_boleto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parcela_id INTEGER NOT NULL REFERENCES consorcio_boleto(id) ON DELETE CASCADE,
    marco INTEGER NOT NULL,
    data_vencimento TEXT,
    canal TEXT,
    destino TEXT,
    resultado TEXT,
    enviado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_notif_consorcio_boleto_unico
    ON notificacao_consorcio_boleto (parcela_id, marco, data_vencimento);

-- fluxo de caixa: saídas (contas a pagar)
CREATE TABLE IF NOT EXISTS saida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    descricao TEXT NOT NULL,
    categoria_id INTEGER REFERENCES categoria_saida(id),
    forma_pagamento_id INTEGER REFERENCES forma_pagamento(id),
    valor REAL,
    data_vencimento TEXT,          -- ISO AAAA-MM-DD
    data_pagamento TEXT,           -- NULL = ainda não paga
    numero_parcela TEXT,           -- livre ("3/6"), ou vazio
    fixo_mensal INTEGER NOT NULL DEFAULT 0,
    serie_id TEXT,                 -- mesmo token nas linhas geradas juntas (parcelamento / série mensal)
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- eventos criados no Google Agenda (1 por apólice/parcela) para não duplicar
CREATE TABLE IF NOT EXISTS evento_agenda (
    chave TEXT PRIMARY KEY,          -- 'vigencia:<apolice_id>' | 'boleto:<parcela_id>'
    event_id TEXT NOT NULL,
    data_ref TEXT,                   -- data do evento na última sincronização
    resumo TEXT,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
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
        "nome": "TEXT", "tipo_pessoa": "TEXT NOT NULL DEFAULT 'F'",
        "data_nascimento": "TEXT", "sexo": "TEXT", "cpf": "TEXT",
        "end_rua": "TEXT", "end_numero": "TEXT", "end_complemento": "TEXT", "end_bairro": "TEXT",
        "end_cep": "TEXT", "end_cidade": "TEXT", "end_estado": "TEXT",
        "tel_ddd": "TEXT", "tel_numero": "TEXT", "email": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "tipo_seguro": {"nome": "TEXT"},
    "forma_pagamento": {"nome": "TEXT"},
    "seguradora": {"nome": "TEXT"},
    "categoria_saida": {"nome": "TEXT"},
    "tipo_consorcio": {"nome": "TEXT"},
    "cotacao_campo": {
        "nome": "TEXT", "tipo": "TEXT", "ordem": "INTEGER NOT NULL DEFAULT 0",
        "papel": "TEXT NOT NULL DEFAULT ''", "opcoes": "TEXT NOT NULL DEFAULT ''",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "apolice": {
        "cliente_id": "INTEGER", "seguradora_id": "INTEGER",
        "tipo_seguro_id": "INTEGER", "numero_apolice": "TEXT",
        "vigencia_inicio": "TEXT", "vigencia_fim": "TEXT",
        "premio_liquido": "REAL", "iof": "REAL", "premio_total": "REAL",
        "forma_pagamento_id": "INTEGER", "comissao_percentual": "REAL",
        "comissao_valor_seguralta_receber": "REAL", "comissao_valor_plenus_receber": "REAL",
        "comissao_valor_seguralta_recebido": "REAL", "comissao_valor_plenus_recebido": "REAL",
        "data_seguralta_recebido": "TEXT", "data_plenus_recebido": "TEXT",
        "plenus_conferido_banco": "INTEGER NOT NULL DEFAULT 0",
        "comissao_parcelada": "INTEGER NOT NULL DEFAULT 0",
        "comissao_cocorretagem": "INTEGER NOT NULL DEFAULT 0",
        "previsto_relatorio_seguralta": "REAL", "recebido_relatorio_seguralta": "REAL",
        "previsto_relatorio_plenus": "REAL", "recebido_relatorio_plenus": "REAL",
        "lancado_quiver": "INTEGER NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "veiculo_placa": "TEXT", "veiculo_descricao": "TEXT",
        "aviso_vigencia_ok": "INTEGER NOT NULL DEFAULT 0", "aviso_vigencia_ok_em": "TEXT",
        "apolice_enviada": "INTEGER NOT NULL DEFAULT 0", "apolice_enviada_data": "TEXT",
        "cartao_enviado": "INTEGER NOT NULL DEFAULT 0", "cartao_enviado_data": "TEXT",
        "observacao": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "apolice_parcela": {
        "apolice_id": "INTEGER", "identificacao": "TEXT", "data": "TEXT", "valor": "REAL",
        "paga": "INTEGER NOT NULL DEFAULT 0", "pago_em": "TEXT",
        "aviso_ok": "INTEGER NOT NULL DEFAULT 0", "aviso_ok_em": "TEXT",
    },
    "apolice_comissao": {
        "apolice_id": "INTEGER", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT", "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "apolice_repasse": {
        "apolice_id": "INTEGER", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT",
        "conferido_banco": "INTEGER NOT NULL DEFAULT 0", "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "apolice_endosso": {
        "apolice_id": "INTEGER", "numero": "TEXT",
        "vigencia_inicio": "TEXT", "vigencia_fim": "TEXT", "motivacao": "TEXT",
        "situacao": "TEXT NOT NULL DEFAULT 'sem_alteracao'", "valor": "REAL",
        "forma_pagamento_id": "INTEGER",
        "veiculo_placa": "TEXT", "veiculo_descricao": "TEXT",
        "comissao_parcelada": "INTEGER NOT NULL DEFAULT 0",
        "comissao_percentual": "REAL",
        "comissao_valor_seguralta_receber": "REAL", "comissao_valor_seguralta_recebido": "REAL",
        "comissao_valor_plenus_receber": "REAL", "comissao_valor_plenus_recebido": "REAL",
        "data_seguralta_recebido": "TEXT", "data_plenus_recebido": "TEXT",
        "plenus_conferido_banco": "INTEGER NOT NULL DEFAULT 0",
        "previsto_relatorio_seguralta": "REAL", "recebido_relatorio_seguralta": "REAL",
        "previsto_relatorio_plenus": "REAL", "recebido_relatorio_plenus": "REAL",
        "lancado_quiver": "INTEGER NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "apolice_endosso_parcela": {
        "endosso_id": "INTEGER", "identificacao": "TEXT", "data": "TEXT", "valor": "REAL",
        "paga": "INTEGER NOT NULL DEFAULT 0", "pago_em": "TEXT",
        "aviso_ok": "INTEGER NOT NULL DEFAULT 0", "aviso_ok_em": "TEXT",
    },
    "apolice_endosso_comissao": {
        "endosso_id": "INTEGER", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT", "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "apolice_endosso_repasse": {
        "endosso_id": "INTEGER", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT",
        "conferido_banco": "INTEGER NOT NULL DEFAULT 0", "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "notificacao_endosso_parcela": {
        "parcela_id": "INTEGER", "marco": "INTEGER", "data_vencimento": "TEXT",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "notificacao_parcela": {
        "parcela_id": "INTEGER", "marco": "INTEGER", "data_vencimento": "TEXT",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "consorcio": {
        "cliente_id": "INTEGER", "seguradora_id": "INTEGER", "tipo_consorcio_id": "INTEGER",
        "carta": "REAL", "numero_grupo": "TEXT", "numero_cota": "TEXT",
        "forma_pagamento_id": "INTEGER", "quantidade_parcelas": "INTEGER",
        "parcela_dia_vencimento": "TEXT",
        "situacao": "TEXT NOT NULL DEFAULT 'ativo'",
        "forma_contemplacao": "TEXT", "data_contemplacao": "TEXT",
        "comissao_percentual": "REAL",
        "comissao_valor_seguralta_receber": "REAL", "comissao_valor_plenus_receber": "REAL",
        "comissao_valor_seguralta_recebido": "REAL", "comissao_valor_plenus_recebido": "REAL",
        "data_seguralta_recebido": "TEXT", "data_plenus_recebido": "TEXT",
        "plenus_conferido_banco": "INTEGER NOT NULL DEFAULT 0",
        "comissao_parcelada": "INTEGER NOT NULL DEFAULT 0",
        "comissao_cocorretagem": "INTEGER NOT NULL DEFAULT 0",
        "previsto_relatorio_seguralta": "REAL", "recebido_relatorio_seguralta": "REAL",
        "previsto_relatorio_plenus": "REAL", "recebido_relatorio_plenus": "REAL",
        "lancado_quiver": "INTEGER NOT NULL DEFAULT 0", "link_onedrive": "TEXT",
        "observacao": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "consorcio_parcela_valor": {
        "consorcio_id": "INTEGER", "valor": "REAL", "data": "TEXT",
        "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "consorcio_comissao": {
        "consorcio_id": "INTEGER", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT", "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "consorcio_repasse": {
        "consorcio_id": "INTEGER", "parcela": "TEXT", "valor_previsto": "REAL",
        "valor_recebido": "REAL", "data": "TEXT",
        "conferido_banco": "INTEGER NOT NULL DEFAULT 0", "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "consorcio_boleto": {
        "consorcio_id": "INTEGER", "identificacao": "TEXT", "valor": "REAL",
        "data_emissao": "TEXT", "data_vencimento": "TEXT", "data_pagamento": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'a_enviar'",
        "aviso_ok": "INTEGER NOT NULL DEFAULT 0", "aviso_ok_em": "TEXT",
        "ordem": "INTEGER NOT NULL DEFAULT 0",
    },
    "notificacao_consorcio_boleto": {
        "parcela_id": "INTEGER", "marco": "INTEGER", "data_vencimento": "TEXT",
        "canal": "TEXT", "destino": "TEXT", "resultado": "TEXT",
        "enviado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "evento_agenda": {
        "chave": "TEXT", "event_id": "TEXT", "data_ref": "TEXT", "resumo": "TEXT",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
    "saida": {
        "descricao": "TEXT", "categoria_id": "INTEGER", "forma_pagamento_id": "INTEGER",
        "valor": "REAL",
        "data_vencimento": "TEXT", "data_pagamento": "TEXT", "numero_parcela": "TEXT",
        "fixo_mensal": "INTEGER NOT NULL DEFAULT 0", "serie_id": "TEXT",
        "criado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
        "atualizado_em": "TEXT NOT NULL DEFAULT (datetime('now'))",
    },
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
        _backfill_dados(con)


def _migrar_esquema(con):
    for tabela, colunas in _COLUNAS_ESPERADAS.items():
        existentes = {l["name"] for l in con.execute(f"PRAGMA table_info({tabela})")}
        if not existentes:
            continue  # tabela nem existe ainda (criada pelo _ESQUEMA_SQL acima) - nada a migrar
        for coluna, definicao in colunas.items():
            if coluna not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def _backfill_dados(con):
    """Preenchimentos únicos de dados após a migração de esquema (só coisas idempotentes)."""
    cols = {l["name"] for l in con.execute("PRAGMA table_info(apolice)")}
    # comissao_valor (coluna antiga) -> comissao_valor_seguralta_receber
    if {"comissao_valor", "comissao_valor_seguralta_receber"} <= cols:
        con.execute(
            "UPDATE apolice SET comissao_valor_seguralta_receber = comissao_valor "
            "WHERE comissao_valor_seguralta_receber IS NULL AND comissao_valor IS NOT NULL"
        )

    # apolice_repasse: valor/status/data_pagamento -> valor_previsto/valor_recebido/data
    rep = {l["name"] for l in con.execute("PRAGMA table_info(apolice_repasse)")}
    if {"valor", "status", "data_pagamento", "valor_previsto"} <= rep:
        con.execute(
            "UPDATE apolice_repasse SET "
            "  valor_previsto = valor, "
            "  valor_recebido = CASE WHEN status = 'pago' THEN valor END, "
            "  data = data_pagamento "
            "WHERE valor_previsto IS NULL AND valor IS NOT NULL"
        )

    # cotacao_campo.papel: 1ª migração herda os papéis dos nomes usados até agora
    # ("Valor do Seguro" / "Nº de Parcelas"). Só roda quando NENHUM campo tem papel,
    # pra nunca brigar com a escolha feita na tela depois.
    cc = {l["name"] for l in con.execute("PRAGMA table_info(cotacao_campo)")}
    if "papel" in cc:
        ja_tem = con.execute(
            "SELECT COUNT(*) FROM cotacao_campo WHERE papel IS NOT NULL AND papel <> ''"
        ).fetchone()[0]
        if not ja_tem:
            def _n(s):
                t = unicodedata.normalize("NFKD", (s or "").strip().lower())
                return "".join(c for c in t if not unicodedata.combining(c))
            usados = set()
            for cid, nome in con.execute("SELECT id, nome FROM cotacao_campo ORDER BY ordem, id").fetchall():
                n = _n(nome)
                if n == "valor do seguro" and "base_parcelamento" not in usados:
                    con.execute("UPDATE cotacao_campo SET papel = 'base_parcelamento' WHERE id = ?", (cid,))
                    usados.add("base_parcelamento")
                elif n == "no de parcelas" and "num_parcelas" not in usados:
                    con.execute("UPDATE cotacao_campo SET papel = 'num_parcelas' WHERE id = ?", (cid,))
                    usados.add("num_parcelas")

    # tipos antigos 'nivel' / 'livre_referenciada' viram 'selecao' com as opções fixas
    # copiadas para a coluna `opcoes`. Idempotente: some quando não há mais esses tipos.
    if "opcoes" in cc:
        for tipo_antigo, opcoes in (("nivel", "Simples\nIntermediário\nCompleto"),
                                    ("livre_referenciada", "Livre escolha\nReferenciada")):
            con.execute(
                "UPDATE cotacao_campo SET tipo = 'selecao', opcoes = ? "
                "WHERE tipo = ? AND (opcoes IS NULL OR opcoes = '')",
                (opcoes, tipo_antigo),
            )


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
