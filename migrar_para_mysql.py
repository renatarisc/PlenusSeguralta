"""Carga unica: copia todos os dados do SQLite legado (plenus.db) para o MySQL (schema
`plenus`), preservando os `id`.

    venv\\Scripts\\python.exe migrar_para_mysql.py [--seco] [--forcar]

--seco     nao grava nada; so mostra as contagens de origem e o que faria.
--forcar   ignora as travas (schema != 'plenus' ou tabelas ja com linhas).

O plenus.db e aberto SOMENTE LEITURA (nunca e alterado). Roda com FOREIGN_KEY_CHECKS=0
durante a carga. Ao final compara COUNT(*) tabela a tabela e falha se divergir.
"""

import sqlite3
import sys

import db

# ordem pai -> filho (com FK_CHECKS=0 nem precisaria, mas ajuda a ler o log)
_ORDEM = [
    "usuario", "cliente", "tipo_seguro", "forma_pagamento", "seguradora",
    "categoria_saida", "tipo_consorcio", "cotacao_campo",
    "apolice", "apolice_parcela", "apolice_comissao", "apolice_repasse",
    "apolice_endosso", "apolice_endosso_parcela", "apolice_endosso_comissao",
    "apolice_endosso_repasse",
    "notificacao_vencimento", "notificacao_parcela", "notificacao_endosso_parcela",
    "consorcio", "consorcio_parcela_valor", "consorcio_comissao", "consorcio_repasse",
    "consorcio_boleto", "notificacao_consorcio_boleto",
    "saida", "evento_agenda",
]

# tipos MySQL em que '' (string vazia vinda do SQLite) tem que virar NULL, senao o
# modo estrito (STRICT_TRANS_TABLES) recusa a linha
_TIPOS_NAO_TEXTO = {"int", "bigint", "smallint", "tinyint", "decimal", "double", "float",
                    "datetime", "date", "timestamp", "time", "year"}


def _tipos_colunas(con, tabela):
    """{coluna_lower: data_type} do schema de destino."""
    base = db.config_db()["database"]
    return {r["c"].lower(): r["t"].lower() for r in con.execute(
        "SELECT column_name AS c, data_type AS t FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s", (base, tabela)).fetchall()}


def _tabelas_sqlite(sq):
    return {r[0] for r in sq.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _tabelas_mysql(con):
    base = db.config_db()["database"]
    return {r["c"] for r in con.execute(
        "SELECT table_name AS c FROM information_schema.tables WHERE table_schema = %s",
        (base,)).fetchall()}


def _conta_mysql(con, tabela):
    return db._um(con.execute(f"SELECT COUNT(*) FROM `{tabela}`"))


def main(argv):
    seco = "--seco" in argv
    forcar = "--forcar" in argv

    cfg = db.config_db()
    if cfg["database"] != "plenus" and not forcar:
        print(f"ABORTADO: o banco de destino e '{cfg['database']}', esperava 'plenus'. "
              f"Use --forcar se for proposital.")
        return 1

    sq = sqlite3.connect(f"file:{db.CAMINHO_DB}?mode=ro", uri=True)
    sq.row_factory = sqlite3.Row

    tab_sq = _tabelas_sqlite(sq)
    print(f"Tabelas no SQLite: {len(tab_sq)}")

    # cria/atualiza o esquema no MySQL antes de carregar
    if not seco:
        db.inicializar_db()

    with db.conexao() as con:
        tab_my = _tabelas_mysql(con)

        ordem = [t for t in _ORDEM if t in tab_sq]
        for t in sorted(tab_sq - set(_ORDEM)):
            ordem.append(t)
            print(f"AVISO: tabela '{t}' fora da ordem conhecida, sera carregada por ultimo.")
        if not seco:
            faltando = [t for t in ordem if t not in tab_my]
            for t in faltando:
                print(f"AVISO: tabela '{t}' existe no SQLite mas nao no MySQL - PULADA.")
            ordem = [t for t in ordem if t in tab_my]

        # trava: destino nao pode ter dado (a menos de --forcar)
        if not forcar and not seco:
            nao_vazias = [t for t in ordem if _conta_mysql(con, t) > 0]
            if nao_vazias:
                print(f"ABORTADO: ja ha linhas no MySQL em: {', '.join(nao_vazias)}. "
                      f"Use --forcar pra carregar por cima.")
                return 1

        origem_counts = {}
        for t in ordem:
            origem_counts[t] = sq.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]

        print("\nContagem de origem (SQLite):")
        for t in ordem:
            print(f"  {t:32} {origem_counts[t]:>6}")

        if seco:
            print("\n[SECO] Nada gravado.")
            return 0

        con.execute("SET FOREIGN_KEY_CHECKS = 0")
        total = 0
        for t in ordem:
            linhas = sq.execute(f"SELECT * FROM '{t}'").fetchall()
            if not linhas:
                continue
            tipos = _tipos_colunas(con, t)   # colunas que existem no destino
            src_cols = list(linhas[0].keys())
            cols = [c for c in src_cols if c.lower() in tipos]
            ignoradas = [c for c in src_cols if c.lower() not in tipos]
            if ignoradas:
                print(f"  (col. orfas ignoradas em {t}: {', '.join(ignoradas)})")
            idx = [src_cols.index(c) for c in cols]
            nulaveis = {j for j, c in enumerate(cols)
                        if tipos.get(c.lower()) in _TIPOS_NAO_TEXTO}
            marc = ", ".join(["%s"] * len(cols))
            col_sql = ", ".join(f"`{c}`" for c in cols)
            dados = []
            for row in linhas:
                vals = [row[i] for i in idx]
                for j in nulaveis:
                    if vals[j] == "":
                        vals[j] = None
                dados.append(vals)
            con.executemany(
                f"INSERT INTO `{t}` ({col_sql}) VALUES ({marc})", dados)
            total += len(dados)
            print(f"  carregado {t:32} {len(dados):>6}")
        con.execute("SET FOREIGN_KEY_CHECKS = 1")

    print(f"\nTotal de linhas inseridas: {total}")

    # conferencia de contagem
    print("\nConferencia SQLite x MySQL:")
    ok = True
    with db.conexao() as con:
        for t in ordem:
            n_my = _conta_mysql(con, t)
            n_sq = origem_counts[t]
            marca = "OK " if n_my == n_sq else "!! "
            if n_my != n_sq:
                ok = False
            print(f"  {marca}{t:32} sqlite={n_sq:>6}  mysql={n_my:>6}")

    sq.close()
    if not ok:
        print("\nFALHOU: alguma tabela nao bateu a contagem.")
        return 1
    print("\nOK: todas as tabelas bateram. plenus.db permanece intacto.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
