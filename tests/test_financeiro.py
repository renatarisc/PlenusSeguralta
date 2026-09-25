"""Comissão pela grade de Entradas (4 donos), recibo × cocorretagem, panorama, conta corrente
e as telas financeiras."""

import db
import repo
from tests.base import TesteBase

PARC = {"comissao_parcelada": "1", "voltar": "/financeiro/entradas",
        "comissao_parcela": ["1", "2"], "comissao_previsto": ["100,00", "100,00"],
        "comissao_recebido": ["100,00", ""], "comissao_data": ["2001-05-06", ""],
        "repasse_parcela": ["1", "2"], "repasse_previsto": ["75,00", "75,00"],
        "repasse_recebido": ["75,00", ""], "repasse_data": ["2001-05-07", ""],
        "repasse_deposito_cc": ["", ""]}
UNICA = {"comissao_parcelada": "0", "voltar": "/financeiro/entradas",
         "comissao_valor_seguralta_receber": "200,00", "comissao_valor_seguralta_recebido": "199,99",
         "comissao_valor_plenus_receber": "150,00", "comissao_valor_plenus_recebido": "149,99",
         "data_seguralta_recebido": "2001-05-06", "data_plenus_recebido": "2001-05-07",
         "data_deposito_cc": ""}


class TestFinanceiro(TesteBase):
    def setUp(self):
        super().setUp()
        self.cid = self.novo_cliente("CLIENTE FIN")
        self.seg = self.id_simples("seguradora")
        self.aid = self.nova_apolice(self.cid, "AP-FIN")
        self.eid = repo.criar_endosso({"apolice_id": str(self.aid), "numero": "E-FIN",
                                       "situacao": "onus", "valor": "100,00"})
        self.sid = repo.criar_servico({"cliente_id": str(self.cid), "apolice_id": str(self.aid),
                                       "tipo_servico_id": str(self.id_simples("tipo_servico")),
                                       "seguradora_id": str(self.seg)})
        self.coid = repo.criar_consorcio({"cliente_id": str(self.cid), "seguradora_id": str(self.seg),
                                          "tipo_consorcio_id": str(self.id_simples("tipo_consorcio")),
                                          "carta": "1000", "situacao": "ativo"})

    def test_grade_de_entradas_nos_quatro_donos(self):
        donos = {"apolice": (self.aid, "", "apolice", "apolice_repasse", "apolice_id"),
                 "endosso": (self.eid, "endosso/", "apolice_endosso", "apolice_endosso_repasse", "endosso_id"),
                 "servico": (self.sid, "servico/", "servico", "servico_repasse", "servico_id"),
                 "consorcio": (self.coid, "consorcio/", "consorcio", "consorcio_repasse", "consorcio_id")}
        for dono, (did, prefixo, tab, trep, col) in donos.items():
            with self.subTest(dono=dono):
                cons = dono == "consorcio"
                extra = {"repasse_conferido": ["1", "0"]} if cons else {"repasse_recibo_id": ["", ""]}
                self.cli.post(f"/financeiro/entradas/{prefixo}{did}/comissoes", data={**PARC, **extra})
                rep = self.sql(f"SELECT * FROM {trep} WHERE {col}=%s ORDER BY ordem", (did,))
                self.assertEqual([r["valor_recebido"] for r in rep], [75, None])
                if cons:
                    self.assertEqual([r["conferido_banco"] for r in rep], [1, 0])
                extra = {"plenus_conferido_banco": "1"} if cons else {"recibo_id": ""}
                self.cli.post(f"/financeiro/entradas/{prefixo}{did}/comissoes", data={**UNICA, **extra})
                linha = self.sql(f"SELECT * FROM {tab} WHERE id=%s", (did,))[0]
                self.assertEqual(linha["comissao_valor_plenus_recebido"], 149.99)
                self.assertEqual(linha["data_plenus_recebido"], "2001-05-07")

    def test_recibo_ignora_endosso_em_cocorretagem_mas_mantem_vinculo(self):
        with db.conexao() as con:
            con.execute("UPDATE apolice_endosso SET comissao_cocorretagem=1, comissao_parcelada=1 WHERE id=%s", (self.eid,))
            con.execute("INSERT INTO apolice_endosso_repasse (endosso_id, parcela, valor_recebido, data, ordem) "
                        "VALUES (%s, '1', 12.34, '2001-02-03', 0)", (self.eid,))
        cand = lambda rid=None: [c for c in repo.parcelas_repasse_por_data("2001-02-03", rid)
                                 if c["origem"] == "endosso_repasse" and "AP-FIN" in c["numero_apolice"]]
        self.assertEqual(cand(), [])
        rid = repo.criar_recibo({"numero": "R-FIN", "data": "2001-02-03"})
        with db.conexao() as con:
            con.execute("UPDATE apolice_endosso_repasse SET recibo_id=%s WHERE endosso_id=%s", (rid, self.eid))
        self.assertEqual(len(cand(rid)), 1)

    def test_endosso_cocorretagem_no_panorama_e_relatorio(self):
        repo.salvar_comissao_unica("endosso", self.eid, {"comissao_valor_plenus_receber": 15.0,
                                                         "comissao_valor_plenus_recebido": 15.0,
                                                         "data_plenus_recebido": "2001-03-04"})
        with db.conexao() as con:
            con.execute("UPDATE apolice_endosso SET comissao_cocorretagem=1, comissao_percentual=10 WHERE id=%s", (self.eid,))
        pan = [x for x in repo.panorama_comissoes() if x.get("endosso_id") == self.eid]
        self.assertEqual(pan[0]["cocorretagem"], 1)
        ent = [x for x in repo.listar_entradas_repasse()
               if x.get("apolice_id") == self.aid and x.get("origem") == "endosso"]
        self.assertEqual(ent[0]["comissao_cocorretagem"], 1)

    def test_cocorretagem_de_servico_na_conta_corrente(self):
        with db.conexao() as con:
            con.execute("UPDATE servico SET comissao_cocorretagem=1, comissao_valor_plenus_recebido=37.5, "
                        "data_deposito_cc='2001-06-07' WHERE id=%s", (self.sid,))
        mov = [m for m in repo.extrato_conta_corrente()
               if m["origem"] == "cocorretagem" and m["data"] == "2001-06-07"]
        self.assertEqual(len(mov), 1)
        self.assertIn("AP-FIN", mov[0]["descricao"])

    def test_telas_financeiras_abrem(self):
        for url in ("/financeiro/entradas", "/financeiro/entradas/panorama",
                    "/financeiro/relatorios/entradas", "/financeiro/relatorios/entradas/pdf",
                    "/financeiro/relatorios/saidas", "/financeiro/conta-corrente",
                    "/recibos", "/notas-fiscais", "/"):
            with self.subTest(url=url):
                self.assertEqual(self.cli.get(url).status_code, 200)
