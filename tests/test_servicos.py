"""Módulo Serviços: cadastro ligado a uma apólice do cliente, lista, filtros, avisos."""

from datetime import date, timedelta

import avisos
import notificacoes
import repo
from tests.base import TesteBase

HOJE = date.today().isoformat()
D5 = (date.today() + timedelta(days=5)).isoformat()
D35 = (date.today() + timedelta(days=35)).isoformat()


class TestServicos(TesteBase):
    def setUp(self):
        super().setUp()
        self.cid = self.novo_cliente("CLIENTE SERVICO")
        self.aid = self.nova_apolice(self.cid, "AP-SERV")
        self.tid = self.id_simples("tipo_servico")
        self.form = {
            "cliente_id": self.cid, "apolice_id": self.aid, "tipo_servico_id": self.tid,
            "seguradora_id": self.id_simples("seguradora"), "numero_proposta": "PROP-1",
            "vigencia_inicio": HOJE, "vigencia_fim": D35,
            "premio_liquido": "1.000,00", "iof": "73,80", "premio_total": "1.073,80",
            "forma_pagamento_id": self.id_simples("forma_pagamento", "boleto"),
            "comissao_percentual": "20", "comissao_parcelada": "1", "lancado_quiver": "1",
            **self.form_parcelas([(None, "1/2", D5, "536,90", "0", "0", "0"),
                                  (None, "2/2", D35, "536,90", "0", "0", "0")]),
            "comissao_parcela": ["1"], "comissao_previsto": ["200,00"], "comissao_recebido": ["200,00"],
            "comissao_data": [HOJE], "repasse_parcela": ["1"], "repasse_previsto": ["150,00"],
            "repasse_recebido": ["150,00"], "repasse_data": [HOJE], "repasse_recibo_id": [""],
            "repasse_deposito_cc": [""],
        }

    def criar(self, **extra):
        r = self.cli.post("/servicos/novo", data={**self.form, **extra})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:500])
        return max(s["id"] for s in repo.listar_servicos(cliente_id=self.cid))

    def test_cadastro_completo(self):
        sv = repo.obter_servico(self.criar())
        self.assertEqual((sv["apolice_id"], sv["numero_apolice"], sv["numero_proposta"]),
                         (self.aid, "AP-SERV", "PROP-1"))
        self.assertEqual((sv["premio_total"], sv["lancado_quiver"]), (1073.8, 1))
        self.assertEqual((len(sv["parcelas"]), len(sv["comissoes"]), len(sv["repasses"])), (2, 1, 1))

    def test_obrigatorios_e_apolice_de_outro_cliente(self):
        html = self.cli.post("/servicos/novo", data={"cliente_id": ""}).get_data(as_text=True)
        self.assertIn("Selecione o cliente", html)
        outro = self.nova_apolice(self.novo_cliente("OUTRO"), "AP-OUTRO")
        html = self.cli.post("/servicos/novo", data={**self.form, "apolice_id": outro}).get_data(as_text=True)
        self.assertIn("não é deste cliente", html)

    def test_lista_filtros_e_json_de_apolices(self):
        self.criar()
        self.assertIn("CLIENTE SERVICO", self.cli.get("/servicos?busca=prop-1").get_data(as_text=True))
        self.assertIn("CLIENTE SERVICO", self.cli.get(f"/servicos?apolice={self.aid}").get_data(as_text=True))
        self.assertNotIn("CLIENTE SERVICO", self.cli.get("/servicos?quiver=0").get_data(as_text=True))
        j = self.cli.get(f"/servicos/apolices/{self.cid}").get_json()
        self.assertEqual([a["id"] for a in j["apolices"]], [self.aid])
        self.assertIn("Serviços (1)", self.cli.get(f"/apolices/{self.aid}").get_data(as_text=True))

    def test_boletos_avisos_e_email(self):
        sid = self.criar()
        pend = [p for p in repo.parcelas_boleto_pendentes() if p.get("servico_id") == sid]
        self.assertEqual(len(pend), 2)
        a_enviar = [p for p in avisos.itens("boleto_enviar_apolice") if p.get("servico_id") == sid]
        self.assertEqual(len(a_enviar), 1)
        assunto, _ = notificacoes.texto_boleto(pend[0], 5)
        self.assertIn("serviço", assunto)
        self.assertIn(f"/servicos/{sid}", self.cli.get("/").get_data(as_text=True))
        pid = pend[0]["parcela_id"]
        self.cli.post(f"/parcelas/{pid}/pagamento", data={"paga": "1", "origem": "servico", "voltar": "/"})
        self.assertEqual(repo.obter_servico(sid)["parcelas"][0]["paga"], 1)

    def test_apolice_com_servico_nao_pode_ser_excluida(self):
        self.criar()
        r = self.cli.post(f"/apolices/{self.aid}/excluir", follow_redirects=True)
        self.assertIn("serviço(s) vinculado(s)", r.get_data(as_text=True))
        self.assertIsNotNone(repo.obter_apolice(self.aid))
