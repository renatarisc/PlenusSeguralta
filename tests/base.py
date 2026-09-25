"""Base dos testes: banco plenus_teste recriado do zero, backups desligados, cliente HTTP
logado e fábricas de registros (cliente, apólice...) com dados fictícios."""

import os
import unittest

import tests  # noqa: F401  (trava do banco *_teste — precisa vir antes de importar db)
import db

if not db.config_db()["database"].endswith("_teste"):  # segunda trava, já no banco resolvido
    raise SystemExit("Abortado: os testes não rodam fora de um banco *_teste.")

# backups desligados: o dump seria do banco de teste e poluiria backups/
db.fazer_backup = lambda *a, **k: None
import repo  # noqa: E402

repo.fazer_backup = db.fazer_backup

_preparado = False


def preparar_banco():
    """Apaga todas as tabelas do plenus_teste e recria o esquema (uma vez por execução)."""
    global _preparado
    if _preparado:
        return
    nome = db.config_db()["database"]
    assert nome.endswith("_teste"), nome
    with db.conexao() as con:
        con.execute("SET FOREIGN_KEY_CHECKS = 0")
        for r in con.execute("SELECT table_name t FROM information_schema.tables "
                             "WHERE table_schema = %s", (nome,)).fetchall():
            con.execute(f"DROP TABLE `{r['t']}`")
        con.execute("SET FOREIGN_KEY_CHECKS = 1")
    db.inicializar_db()
    _preparado = True


class TesteBase(unittest.TestCase):
    _cpf = 0

    @classmethod
    def setUpClass(cls):
        preparar_banco()
        import app as appmod
        cls.app = appmod.app
        cls.app.config.update(WTF_CSRF_ENABLED=False, TESTING=True)
        teste = next((u for u in repo.listar_usuarios() if u["login"] == "teste"), None)
        cls.uid = teste["id"] if teste else repo.criar_usuario("Teste", "teste", "senhaTeste123")
        if not repo.listar_simples("seguradora"):
            repo.criar_simples("seguradora", "Seguradora Teste")
        if not repo.listar_simples("forma_pagamento"):
            repo.criar_simples("forma_pagamento", "Boleto")
            repo.criar_simples("forma_pagamento", "Cartão")
        if not repo.listar_simples("tipo_servico"):
            repo.criar_simples("tipo_servico", "Assistência")
        if not repo.listar_simples("tipo_consorcio"):
            repo.criar_simples("tipo_consorcio", "Imóvel")

    def setUp(self):
        self.cli = self.app.test_client()
        with self.cli.session_transaction() as s:
            s["usuario_id"] = self.uid
            s["usuario_nome"] = "Teste"

    # ---------- utilidades ----------
    @staticmethod
    def sql(q, p=()):
        with db.conexao() as con:
            return [dict(r) for r in con.execute(q, p).fetchall()]

    @staticmethod
    def id_simples(tabela, parte_nome=""):
        return next(x["id"] for x in repo.listar_simples(tabela)
                    if parte_nome.lower() in x["nome"].lower())

    @classmethod
    def novo_cpf(cls):
        """CPF válido e único por teste (gerado pelos dígitos verificadores)."""
        TesteBase._cpf += 1
        base = f"{100000000 + TesteBase._cpf:09d}"
        for n in (10, 11):
            soma = sum(int(d) * (n - i) for i, d in enumerate(base))
            base += str((soma * 10 % 11) % 10)
        return base

    def novo_cliente(self, nome="CLIENTE TESTE"):
        return repo.criar_cliente({"nome": nome, "tipo_pessoa": "F", "cpf": self.novo_cpf()})

    def nova_apolice(self, cliente_id, numero="AP-1", parcelas=None, **extra):
        dados = {"cliente_id": str(cliente_id), "seguradora_id": str(self.id_simples("seguradora")),
                 "numero_apolice": numero, **extra}
        return repo.criar_apolice(dados, parcelas or [])

    @staticmethod
    def form_parcelas(linhas):
        """linhas: [(id, identificacao, data, valor, paga, aviso, enviado)]"""
        return {"parcela_id": [str(l[0] or "") for l in linhas],
                "parcela_identificacao": [l[1] for l in linhas],
                "parcela_data": [l[2] for l in linhas], "parcela_valor": [l[3] for l in linhas],
                "parcela_paga": [l[4] for l in linhas], "parcela_aviso": [l[5] for l in linhas],
                "parcela_enviado": [l[6] for l in linhas]}
