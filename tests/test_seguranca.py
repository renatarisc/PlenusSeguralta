"""Acesso e proteções: sessão de usuário desativado, confirmações com apóstrofo,
exclusões bloqueadas, rateio repassado aos formulários."""

import repo
from tests.base import TesteBase


class TestSeguranca(TesteBase):
    def test_sem_login_vai_para_o_login(self):
        cli = self.app.test_client()
        r = cli.get("/apolices")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_usuario_desativado_perde_a_sessao(self):
        uid = repo.criar_usuario("Outra Pessoa", "outra_pessoa", "senhaTeste123")
        cli = self.app.test_client()
        with cli.session_transaction() as s:
            s["usuario_id"] = uid
        self.assertEqual(cli.get("/").status_code, 200)
        r = cli.post(f"/usuarios/{uid}", data={"nome": "Outra Pessoa", "login": "outra_pessoa", "ativo": "0"})
        self.assertIn("não pode desativar o próprio usuário", r.get_data(as_text=True))
        repo.atualizar_usuario(uid, "Outra Pessoa", "outra_pessoa", False)
        r = cli.get("/")
        self.assertIn("/login", r.headers.get("Location", ""))
        with cli.session_transaction() as s:
            self.assertNotIn("usuario_id", s)
        repo.excluir_usuario(uid)

    def test_ultimo_usuario_ativo_nao_pode_ser_desativado(self):
        ativos = [u for u in repo.listar_usuarios() if u["ativo"]]
        unico = next(u for u in ativos if u["id"] == self.uid)
        outros = [u for u in ativos if u["id"] != self.uid]
        for u in outros:
            repo.atualizar_usuario(u["id"], u["nome"], u["login"], False)
        outro = None
        try:
            outro = repo.criar_usuario("Admin 2", "admin_dois", "senhaTeste123")
            repo.atualizar_usuario(outro, "Admin 2", "admin_dois", False)
            cli = self.app.test_client()
            with cli.session_transaction() as s:
                s["usuario_id"] = unico["id"]
            r = cli.post(f"/usuarios/{unico['id']}",
                         data={"nome": unico["nome"], "login": unico["login"], "ativo": "0"})
            self.assertIn("não pode desativar", r.get_data(as_text=True))
            self.assertEqual(repo.obter_usuario(unico["id"])["ativo"], 1)
        finally:
            for u in outros:
                repo.atualizar_usuario(u["id"], u["nome"], u["login"], True)
            if outro:
                repo.excluir_usuario(outro)

    def test_confirmacao_com_apostrofo(self):
        cid = self.novo_cliente("Joana D'Arc")
        html = self.cli.get(f"/clientes/{cid}").get_data(as_text=True)
        self.assertIn('data-confirmar="Excluir o cliente Joana D&#39;Arc?', html)
        self.assertNotIn("return confirm(", html)

    def test_apolice_com_endosso_nao_pode_ser_excluida(self):
        aid = self.nova_apolice(self.novo_cliente(), "AP-SEG")
        eid = repo.criar_endosso({"apolice_id": str(aid), "numero": "E", "situacao": "sem_alteracao"})
        r = self.cli.post(f"/apolices/{aid}/excluir", follow_redirects=True)
        self.assertIn("tem 1 endosso(s)", r.get_data(as_text=True))
        self.assertIsNotNone(repo.obter_endosso(eid))
        repo.excluir_endosso(eid)
        self.cli.post(f"/apolices/{aid}/excluir")
        self.assertIsNone(repo.obter_apolice(aid))

    def test_formularios_recebem_o_rateio_e_o_comissao_js_unico(self):
        for url in ("/apolices/nova", "/endossos/novo", "/consorcios/novo", "/servicos/novo"):
            with self.subTest(url=url):
                html = self.cli.get(url).get_data(as_text=True)
                self.assertIn('window.PLENUS_RATEIO = {"plenus": 75, "seguralta_coco": 25}', html)
                self.assertIn("js/comissao.js", html)
                self.assertIn('id="comissao-unico"', html)
